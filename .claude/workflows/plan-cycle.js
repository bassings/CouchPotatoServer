export const meta = {
  name: 'plan-cycle',
  description: 'Multi-lens planning cycle: triggered lenses write AC-<LENS>-<n> criteria into the spec, per AGENT-HARNESS.md',
  whenToUse: 'After drafting a spec, before implementation. Args: {spec: string (path to the spec, required), lenses?: string[] (override triggering)}',
  phases: [
    { title: 'Scope', detail: 'read the spec, classify the change surface' },
    { title: 'Lenses', detail: 'triggered lenses draft acceptance criteria in parallel' },
    { title: 'Synthesis', detail: 'merge criteria, apply the simplicity veto, write the AC block into the spec' },
  ],
}

// args can arrive as a JSON-encoded string depending on the caller; normalise before use
let opts = args
if (typeof opts === 'string') { try { opts = JSON.parse(opts) } catch (e) { opts = null } }
opts = opts || {}
if (typeof opts !== 'object' || !opts.spec) throw new Error('plan-cycle requires args.spec: the path to the spec file to plan against')
const specPath = opts.spec

// ---- Phase 1: scope ----
phase('Scope')
const scope = await agent(
  `Read the spec at ${specPath} and skim the repo areas it names. Classify the change surface, returning raw booleans:\n` +
  `- ui: does it touch UI, templates, styles or user-facing copy (couchpotato/ui, templates, static, *.html, tests/e2e)?\n` +
  `- data: does it touch schema, migrations, destructive file or DB operations, or personal data (couchpotato/core/db, database.py, renamer, scanner, release plugins)?\n` +
  `- architecture: does it add a module, package, dependency, or touch event.py / loader.py / api.py / couchpotato/__init__.py?\n` +
  `- operability: does it change production behaviour, logging, Docker, CI or scripts?\n` +
  `- user_facing: will a user see or feel this change?\n` +
  `Also return a two-sentence summary of what the spec asks for, and the list of repo paths it will most likely touch.`,
  {
    label: 'scope:spec',
    phase: 'Scope',
    effort: 'low',
    schema: {
      type: 'object',
      required: ['summary', 'ui', 'data', 'architecture', 'operability', 'user_facing', 'likely_paths'],
      properties: {
        summary: { type: 'string' },
        ui: { type: 'boolean' },
        data: { type: 'boolean' },
        architecture: { type: 'boolean' },
        operability: { type: 'boolean' },
        user_facing: { type: 'boolean' },
        likely_paths: { type: 'array', items: { type: 'string' } },
      },
    },
  }
)
if (!scope) return { report: 'Scope agent failed; no plan produced.' }

// ---- deterministic lens triggering (AGENTS.md rules; simplicity is planning-only and always on) ----
let lenses = ['lens-security', 'lens-qa', 'lens-simplicity', 'lens-product']
if (scope.ui) lenses.push('lens-design', 'lens-accessibility')
if (scope.data) lenses.push('lens-data')
if (scope.architecture) lenses.push('lens-architecture')
if (scope.operability) lenses.push('lens-operability')
if (Array.isArray(opts.lenses) && opts.lenses.length) lenses = opts.lenses.slice()

const ALL = ['lens-security', 'lens-qa', 'lens-simplicity', 'lens-product', 'lens-design', 'lens-accessibility', 'lens-data', 'lens-architecture', 'lens-operability']
const skipped = ALL.filter(l => !lenses.includes(l))
log(`Planning ${specPath}: ${scope.summary} Lenses: ${lenses.join(', ')}. Skipped (not triggered): ${skipped.join(', ') || 'none'}.`)

// ---- Phase 2: lenses in parallel (planning is read-only, no isolation needed) ----
const PLAN_SCHEMA = {
  type: 'object',
  required: ['verdict', 'coverage', 'acceptance_criteria'],
  properties: {
    verdict: { type: 'string', enum: ['CLEAN', 'FINDINGS', 'BLOCKED'] },
    coverage: {
      type: 'object',
      required: ['examined', 'verified_by', 'could_not_check'],
      properties: { examined: { type: 'string' }, verified_by: { type: 'string' }, could_not_check: { type: 'string' } },
    },
    acceptance_criteria: { type: 'array', items: { type: 'object', required: ['id', 'statement'], properties: { id: { type: 'string' }, statement: { type: 'string' }, proof_level: { type: 'string' } } } },
    findings: { type: 'array', items: { type: 'object', required: ['severity', 'claim', 'evidence', 'consequence', 'fix'], properties: { severity: { type: 'string', enum: ['Critical', 'High', 'Medium', 'Low'] }, claim: { type: 'string' }, location: { type: 'string' }, evidence: { type: 'string' }, consequence: { type: 'string' }, fix: { type: 'string' } } } },
  },
}

const lensPrompt = (lens) =>
  `PLANNING mode. The spec is at ${specPath}. Likely touched paths: ${scope.likely_paths.join(', ') || 'unknown'}.\n` +
  `Read the spec and the relevant code, then produce your lens's numbered acceptance criteria as AC-<LENS>-<n> ` +
  `(e.g. AC-SEC-1, AC-QA-1, AC-SIMP-1: use your lens's short code). Each statement must be testable: a thing that can be ` +
  `shown true or false against the built change. Do not write criteria for another lens's concern.\n` +
  `Do NOT modify any file, including the spec: the synthesis step writes the criteria in. Return them via the structured ` +
  `output schema, with your coverage statement (could_not_check is mandatory and must be honest). Findings here are ` +
  `problems with the SPEC itself (missing decisions, untestable asks, scope risks). Australian English, no em dashes.`

const reports = await parallel(lenses.map(lens => () =>
  agent(lensPrompt(lens), { agentType: lens, label: lens, phase: 'Lenses', schema: PLAN_SCHEMA })
    .then(r => (r ? { lens, ...r } : null))
))
const lensReports = reports.filter(Boolean)
if (!lensReports.length) return { report: 'Every lens agent failed or was stopped; no plan produced.' }

// ---- Phase 3: synthesis, simplicity veto, write-back ----
phase('Synthesis')
const synthesis = await agent(
  `You are the orchestrator of the multi-lens planning harness in ~/.claude/AGENT-HARNESS.md (read it). ` +
  `Below are the structured planning reports for the spec at ${specPath}.\n\n` +
  `LENS REPORTS (JSON):\n${JSON.stringify(lensReports, null, 1)}\n\n` +
  `Do the following, in order:\n` +
  `1. Apply the simplicity veto: lens-simplicity may reject any criterion or requirement not traceable to the spec's ` +
  `stated goal. A vetoed criterion is DROPPED and recorded, unless it belongs to security, data-loss or the accessibility ` +
  `floor, which simplicity cannot override. Record every veto with its reason.\n` +
  `2. Merge the surviving criteria, deduplicating overlaps (keep the more testable wording; keep both IDs in a note).\n` +
  `3. Edit the spec file at ${specPath}: add or replace a section titled "## Acceptance criteria" containing the surviving ` +
  `AC-<LENS>-<n> lines grouped by lens, each on one line, exactly as the review cycle will verify them. Preserve the rest ` +
  `of the file byte-for-byte. Also add a "### Vetoed at planning" subsection listing the drops and reasons, if any.\n` +
  `4. Return a markdown summary: a per-lens table (verdict, criteria count, could_not_check), the veto list, any lens ` +
  `findings about the spec itself (BLOCKED lenses prominently), and the final AC count.\n` +
  `Australian English, no em dashes. Return only the markdown summary.`,
  { label: 'synthesis:write-back', phase: 'Synthesis' }
)

return {
  spec: specPath,
  lenses,
  skipped,
  verdicts: Object.fromEntries(lensReports.map(r => [r.lens, r.verdict])),
  report: synthesis,
}
