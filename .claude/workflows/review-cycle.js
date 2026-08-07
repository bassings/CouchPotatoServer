export const meta = {
  name: 'review-cycle',
  description: 'Multi-lens review of the branch diff per AGENT-HARNESS.md and the AGENTS.md path triggers',
  whenToUse: 'Before raising a PR, or as the local review gate on a branch. Args: {base?: string (default master), spec?: string, lenses?: string[] (override triggering), adversarial?: boolean (adds reviewer-verification)}',
  phases: [
    { title: 'Scope', detail: 'diff the branch, classify the change surface' },
    { title: 'Lenses', detail: 'triggered lenses review in parallel, isolated worktrees' },
    { title: 'Synthesis', detail: 'dedup, arbitrate by precedence, one report' },
  ],
}

// ---- repo-specific trigger globs (from AGENTS.md "Multi-lens harness" section) ----
const UI_GLOBS = ['couchpotato/ui/**', 'couchpotato/templates/**', '**/*.html', 'couchpotato/static/**', 'tests/e2e/**']
// Resolved from the running environment, never hardcoded. The previous
// version embedded one contributor's macOS checkout and username, so the
// path did not exist for anyone else -- reviewers could not run the pytest
// or mutation checks the prompt asks for, and the gate lost its verification
// evidence. It also sent a private filesystem path to every spawned agent.
const MAIN_REPO = process.cwd()
const MAIN_PYTHON = `${MAIN_REPO}/.venv/bin/python`

const DATA_GLOBS = ['couchpotato/core/db/**', 'couchpotato/core/database.py', '**/schema.sql', 'couchpotato/core/plugins/renamer/**', 'couchpotato/core/plugins/scanner/**', 'couchpotato/core/plugins/release/**']
// `couchpotato/api.py`, NOT `couchpotato/core/api.py`. The latter does not
// exist, so the API boundary never triggered lens-architecture at all. The
// comment lives ABOVE the array, not inside it: a `//` inside an array literal
// swallows the rest of the physical line INCLUDING the closing bracket, which
// is how this line shipped broken.
const ARCH_FILES = [
  'couchpotato/core/event.py',
  'couchpotato/core/loader.py',
  'couchpotato/api.py',
  'couchpotato/__init__.py',
]
const OPS_GLOBS = ['Dockerfile', 'docker-*.yml', '.github/workflows/**', 'couchpotato/core/logger.py', 'scripts/**',
  // Scheduled behaviour is an operability concern wherever it lives, and
  // path globs alone missed it: the commit that added this line changed the
  // scheduled full-library cleanup in plugins/manage.py, which matched none
  // of the globs above, so the cycle skipped lens-operability for its own
  // diff. These are the scheduler's own module and the plugins that register
  // interval jobs.
  'couchpotato/core/_base/scheduler.py', 'couchpotato/core/plugins/manage.py',
  'couchpotato/core/plugins/renamer/main.py', 'couchpotato/core/plugins/automation.py']

function globToRe(g) {
  let s = g.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  s = s.replace(/\*\*/g, '\u0001').replace(/\*/g, '[^/]*').replace(/\u0001/g, '.*')
  return new RegExp('^' + s + '$')
}
function matches(paths, globs) {
  const res = globs.map(globToRe)
  return paths.filter(p => res.some(r => r.test(p)))
}

// args can arrive as a JSON-encoded string depending on the caller; normalise before use
let opts = args
if (typeof opts === 'string') { try { opts = JSON.parse(opts) } catch (e) { opts = null } }
opts = opts || {}

const base = opts.base || 'master'
const specPath = opts.spec || null

// ---- Phase 1: scope ----
phase('Scope')
const scope = await agent(
  `In the repo at the current working directory, run:\n` +
  `  git diff --name-status ${base}...HEAD\n` +
  `and, if any requirements*.txt file changed, also inspect its diff.\n` +
  `Return: every changed file path with its status letter; whether any requirements file gained a NEW entry ` +
  `(a new package, not a version bump of an existing one); and whether the diff ADDS a new Python module or package ` +
  `(a new .py file outside tests/, or a new directory with __init__.py). Also return the exact output of ` +
  `\`git rev-parse HEAD\` as head_sha. Raw data only.`,
  {
    label: 'scope:diff',
    phase: 'Scope',
    effort: 'low',
    schema: {
      type: 'object',
      required: ['files', 'new_requirement_entries', 'new_modules', 'head_sha'],
      properties: {
        files: { type: 'array', items: { type: 'object', required: ['path', 'status'], properties: { path: { type: 'string' }, status: { type: 'string' } } } },
        new_requirement_entries: { type: 'boolean' },
        new_modules: { type: 'boolean' },
        head_sha: { type: 'string' },
      },
    },
  }
)
if (!scope || !scope.files.length) return { report: `No changes found between ${base} and HEAD. Nothing to review.` }

const paths = scope.files.map(f => f.path)
const addedOrModified = scope.files.filter(f => f.status !== 'D').map(f => f.path)

// ---- deterministic lens triggering (AGENTS.md rules) ----
let lenses = ['lens-security', 'lens-qa'] // always on at review
const uiHit = matches(paths, UI_GLOBS)
// `paths`, not `addedOrModified`: deleting a schema, adapter, renamer or
// release file is at least as destructive as modifying one, and filtering
// status 'D' skipped the highest-risk lens for exactly that case.
const dataHit = matches(paths, DATA_GLOBS)
const archHit = matches(paths, ARCH_FILES)
const opsHit = matches(paths, OPS_GLOBS)
const specHit = matches(paths, ['specs/**'])

if (uiHit.length) lenses.push('lens-design', 'lens-accessibility')
if (dataHit.length) lenses.push('lens-data')
if (archHit.length || scope.new_modules || scope.new_requirement_entries) lenses.push('lens-architecture')
if (opsHit.length) lenses.push('lens-operability')
// `specPath` too: a caller can supply an existing, UNCHANGED spec, and a
// user-facing backend change (auth, settings behaviour) touches neither a
// spec file nor a UI glob -- so both documented triggers could be satisfied
// while the lens was skipped.
if (specHit.length || uiHit.length || specPath) lenses.push('lens-product')

// An override ADDS to the mandatory roster, it does not replace it.
// `{lenses: ['lens-data']}` used to silently drop lens-security and lens-qa,
// which AGENT-HARNESS.md makes always-on at review -- so the gate could
// complete having run neither.
const MANDATORY = ['lens-security', 'lens-qa']
if (Array.isArray(opts.lenses) && opts.lenses.length) {
  lenses = [...new Set([...MANDATORY, ...opts.lenses])]
}
if (opts.adversarial) lenses.push('reviewer-verification')

const ALL = ['lens-security', 'lens-qa', 'lens-design', 'lens-accessibility', 'lens-data', 'lens-architecture', 'lens-operability', 'lens-product']
const skipped = ALL.filter(l => !lenses.includes(l))
log(`Reviewing ${paths.length} changed files against ${base}. Lenses: ${lenses.join(', ')}. Skipped (not triggered): ${skipped.join(', ') || 'none'}.`)

// ---- Phase 2: lenses in parallel, each in its own worktree ----
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'coverage', 'findings'],
  properties: {
    verdict: { type: 'string', enum: ['CLEAN', 'FINDINGS', 'BLOCKED'] },
    coverage: {
      type: 'object',
      required: ['examined', 'verified_by', 'could_not_check'],
      properties: { examined: { type: 'string' }, verified_by: { type: 'string' }, could_not_check: { type: 'string' } },
    },
    ac_verdicts: { type: 'array', items: { type: 'object', required: ['id', 'verdict', 'evidence'], properties: { id: { type: 'string' }, verdict: { type: 'string', enum: ['PASS', 'FAIL', 'UNVERIFIABLE'] }, evidence: { type: 'string' } } } },
    findings: { type: 'array', items: { type: 'object', required: ['severity', 'claim', 'location', 'evidence', 'consequence', 'fix'], properties: { severity: { type: 'string', enum: ['Critical', 'High', 'Medium', 'Low'] }, claim: { type: 'string' }, location: { type: 'string' }, evidence: { type: 'string' }, consequence: { type: 'string' }, fix: { type: 'string' } } } },
  },
}

const fileList = paths.slice(0, 120).join('\n')
const specClause = specPath
  ? `The spec for this change is at ${specPath}. Verify each of YOUR lens's AC-<LENS>-<n> criteria against the built change and return ac_verdicts for them. Also report anything you find outside them.`
  : `No spec path was supplied. Check specs/ (including specs files inside this diff) for a spec covering this change; ` +
    `if one exists, verify YOUR lens's AC-<LENS>-<n> criteria from it and return ac_verdicts. Only if none exists, review ` +
    `against your lens rubric alone, return an empty ac_verdicts array, and record the absent spec in could_not_check.`

const qaBudget =
  `Bound your mutation experiments: run at most 8, chosen for the highest-risk guards in the diff (destructive paths, ` +
  `security gates, concurrency locks first). List every guard you deliberately did not mutate in could_not_check; ` +
  `an honest skip list beats an unbounded run.\n`

const lensPrompt = (lens) =>
  `REVIEW mode. The reviewed tip is commit ${scope.head_sha}. First run \`git rev-parse HEAD\` in your worktree; if it ` +
  `differs, your checkout has drifted from the reviewed tip (a parallel session may have advanced the branch): diff ` +
  `against the pinned SHA explicitly and record the drift in could_not_check. Review \`git diff ${base}...${scope.head_sha}\`.\n` +
  `Changed files (${paths.length} total):\n${fileList}\n\n` +
  `${specClause}\n\n` +
  (lens === 'lens-qa' ? qaBudget : '') +
  `You are in an isolated git worktree: mutation experiments (break the guard, watch the test fail, restore) are safe here, ` +
  `but there is no .venv in this worktree. To run Python tests use the main repo's interpreter by absolute path: ` +
  `${MAIN_PYTHON} -m pytest ... from this worktree's root. ` +
  `Never modify anything under ${MAIN_REPO} or its .venv.\n\n` +
  `Your final structured output maps the AGENT-HARNESS.md output contract onto the schema fields: verdict, coverage ` +
  `(could_not_check is mandatory and must be honest, not "nothing"), ac_verdicts, findings (each with file:line in location). ` +
  `You are licensed to return CLEAN with empty findings. Australian English, no em dashes.`

const reports = await parallel(lenses.map(lens => () =>
  agent(lensPrompt(lens), { agentType: lens, label: lens, phase: 'Lenses', schema: REVIEW_SCHEMA, isolation: 'worktree' })
    .then(r => (r ? { lens, ...r } : null))
))
const lensReports = reports.filter(Boolean)
if (!lensReports.length) return { report: 'Every lens agent failed or was stopped; no review produced.' }

// AC-SIMP constraints are mechanical: checked directly against the diff, not by an agent lens (harness rule)
let simpCheck = null
if (specPath) {
  simpCheck = await agent(
    `Read ${specPath}. If it contains AC-SIMP-<n> acceptance criteria, check each one mechanically against ` +
    `\`git diff ${base}...${scope.head_sha}\` (they are constraints like "no new dependency", "no new setting", "no abstraction for a single call site"). ` +
    `Return one verdict per AC-SIMP with the diff evidence. If the spec has none, say so. Raw data only.`,
    { label: 'ac-simp:mechanical', phase: 'Lenses', effort: 'low' }
  )
}

// ---- Phase 3: synthesis ----
phase('Synthesis')
const synthesis = await agent(
  `You are the orchestrator of the multi-lens review harness defined in ~/.claude/AGENT-HARNESS.md (read it). ` +
  `Below are the structured reports from each lens for the branch diff against ${base}.\n\n` +
  `LENS REPORTS (JSON):\n${JSON.stringify(lensReports, null, 1)}\n\n` +
  (simpCheck ? `AC-SIMP MECHANICAL CHECK:\n${simpCheck}\n\n` : '') +
  `Produce the single synthesised review report, in markdown:\n` +
  `1. A verdict table: one row per lens with its verdict and its "could not check" statement.\n` +
  `2. Findings merged and deduplicated (same defect from two lenses is one finding credited to both), ordered by severity ` +
  `(Critical, High, Medium, Low). Keep each finding's location, evidence, consequence and fix.\n` +
  `3. Conflicts between lenses arbitrated by the precedence order: irrecoverable data loss, security, accessibility floor, ` +
  `operability, product and design intent, performance. A tie ABOVE the accessibility line is marked ESCALATE for the human, ` +
  `never resolved silently.\n` +
  `4. ${specPath ? 'AC verdict summary, and any finding with no AC behind it flagged as a SPEC BUG.' : 'Note that no spec existed, so every finding is unanchored to an AC.'}\n` +
  `5. A closing line: overall CLEAN / FINDINGS / BLOCKED and what must happen before push.\n` +
  `Do not soften findings and do not invent any. If a lens returned BLOCKED, say so prominently. ` +
  `Australian English, no em dashes. Return only the markdown report.`,
  { label: 'synthesis', phase: 'Synthesis' }
)

return {
  base,
  lenses,
  skipped,
  verdicts: Object.fromEntries(lensReports.map(r => [r.lens, r.verdict])),
  report: synthesis,
}
