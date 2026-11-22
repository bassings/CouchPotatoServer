// @vitest-environment node
/**
 * SEC-005 D7: a model-based, seeded, randomised test of the Settings page's save bookkeeping
 * (`settingsPanel` saveSingle, flushPendingSavesFor, applyAcceptedSave and `buttonField.execute`
 * in partials/settings/scripts.html).
 *
 * It drives the REAL template script (shared with settings-group-save.spec.ts through
 * ./settings-script) with a seeded random sequence of events: the user types into one of three options
 * of the button's section or one option of another section, time passes (the 500 ms debounce, the 10
 * second wait), the server answers a save (accepts, refuses, or the request fails), and the button is
 * pressed (a second button of the same section too, in the two-button mode). A small model of the
 * server (the last value it accepted per option, and every request it received) and of what the user
 * typed is kept beside it, and after every event the page is checked against it.
 *
 * The six invariants, in plain words:
 *  I1 When an action request goes out, every option of the button's section holds on the server what
 *     the user last TYPED (bar a value typed after that press began, and a late overwrite, below).
 *  I2 Once a save of the section has not landed (refused, failed, or unanswered at its deadline) in a
 *     press, that press sends no further save it queued.
 *  I3 An option the page does not mark as unsaved shows what the server accepted, and the value the
 *     user last typed has not been lost: it is saved, or still marked unsaved.
 *  I4 Every press ends within a bound (one deadline per save ahead of it or queued by it), a stop text
 *     is justified by a save of the section that really did not land, and once the server accepts
 *     everything, one press runs the action and leaves nothing unsaved.
 *  I5 Per section, one save is out at a time inside its deadline; per option, saves are sent in the
 *     order they were queued.
 *  I6 A press never queues a value that is already the last one in flight or queued for that option.
 *
 * Why I1 and I3 compare with what the user TYPED and not with what the field DISPLAYS: the first
 * version compared the server with the displayed value, and three deliberate mutants survived, because
 * the page redisplays whatever the server echoes, so the displayed value follows the server by
 * construction. What the user last typed is the model's own record, which the page cannot overwrite.
 * The one exemption is the recorded late-overwrite limit (spec AC-PROD-12, gap (h)): an answer that
 * arrives after its deadline and lands after a newer value was saved leaves the server on the older
 * value; the page cannot see it.
 *
 * What this model cannot express, and where that is covered instead:
 *  - Combine-group edits. The section may carry a combine group (MODEL_GROUP), but no event edits its
 *    rows, so the guard that takes the open saves before the press's first await (the group flush
 *    awaits the network first) is NOT covered here; settings-group-save.spec.ts has that case.
 *  - Server rewrites of a value (`changed`) and password fields (a server that omits the value).
 *  - Real-network reordering beyond the answers the model chooses, and the page's own re-render.
 *  - Tab changes (the button rebuilt with an empty result region).
 *
 * Knobs (environment variables; the defaults are fixed seeds, so the gate is deterministic):
 *  MODEL_RUNS         sequences per shape (default 100 for each of the two shapes, and 30 for the short
 *                     two-button run: about 230 in all, a few seconds).
 *  MODEL_SEED         the first seed (default 1); a failure prints the seed and a minimal script.
 *  MODEL_GROUP        1: only the shape whose section has a combine group; 0: only the plain shape;
 *                     unset: both.
 *  MODEL_TWO_BUTTONS  1: only the two-button mode (two buttons in one section, overlapping presses);
 *                     unset: the default also runs a short fixed two-button run.
 *  MODEL_STATS        a file to write the counts of what the run exercised (for a human to read).
 * A long soak: `MODEL_RUNS=20000 npx vitest run tests/unit/ui/settings-save-model.spec.ts`
 * (docs/development-process.md).
 */
import fs from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getVal } from '../../../couchpotato/static/scripts/ui/settings-values.js';
import { loadSettingsScript } from './settings-script';

const COMPONENTS = loadSettingsScript();
const DEADLINE: number = COMPONENTS.SAVE_WAIT_DEADLINE_MS;
const DEBOUNCE = 500;

// Whether the section under test carries a combine group; set for each run by the tests at the foot.
let WITH_GROUP = false;

const SECTION = 'jk';
const OTHER = 'other';
const OPTS = [
  { section: SECTION, name: 'url' },
  { section: SECTION, name: 'key' },
  { section: SECTION, name: 'extra' },
  { section: OTHER, name: 'x' },
];
const ALPHABET = ['a', 'b', 'c', '0'];
const ACTION = 'jk.sync';
const ACTION2 = 'jk.test';

// ── PRNG ────────────────────────────────────────────────────────────────────
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ── events ─────────────────────────────────────────────────────────────────
type Ev =
  | { t: 'type'; opt: number; v: string }
  | { t: 'tick'; ms: number }
  | { t: 'answer'; opt: number; how: 'accept' | 'refuse' | 'reject'; late?: boolean; newest?: boolean }
  | { t: 'press' }
  | { t: 'press2' };

function show(e: Ev): string {
  switch (e.t) {
    case 'type': return `type ${OPTS[e.opt].section}.${OPTS[e.opt].name} = '${e.v}'`;
    case 'tick': return `advance ${e.ms} ms`;
    case 'answer': return `answer the ${e.newest ? 'NEWEST' : 'oldest'} open save of ${OPTS[e.opt].section}.${OPTS[e.opt].name}${e.late ? ' that is PAST its deadline' : ''}: ${e.how}`;
    case 'press': return 'press the button';
    case 'press2': return 'press the SECOND button of the section';
  }
}

function genSeq(seed: number, withSecondButton: boolean): Ev[] {
  const rnd = mulberry32(seed);
  const pick = <T>(xs: T[]) => xs[Math.floor(rnd() * xs.length)];
  // Two profiles, alternating by seed: a broad one, and a focused one (one option mostly, two values,
  // debounce-sized ticks, mostly accepts) that reaches the "changed and changed back while in flight" shapes.
  const focused = seed % 2 === 0;
  const n = 20 + Math.floor(rnd() * 41);
  const evs: Ev[] = [];
  for (let i = 0; i < n; i += 1) {
    const r = rnd();
    const q = rnd();
    const opt = focused ? (q < 0.75 ? 0 : q < 0.9 ? 1 : 3) : (q < 0.5 ? 0 : q < 0.75 ? 1 : q < 0.85 ? 2 : 3);
    const values = focused ? ['a', 'b', 'a', 'b', 'c'] : ALPHABET;
    if (r < 0.28) evs.push({ t: 'type', opt, v: pick(values) });
    else if (r < 0.45) evs.push({ t: 'tick', ms: focused ? pick([500, 500, 501, 200]) : pick([50, 200, 499, 500, 501, 600]) });
    else if (r < (focused ? 0.48 : 0.52)) evs.push({ t: 'tick', ms: pick([DEADLINE - 1, DEADLINE, DEADLINE + 1, 2 * DEADLINE]) });
    else if (r < 0.80) {
      const how = focused ? pick(['accept', 'accept', 'accept', 'accept', 'refuse', 'reject'] as const) : pick(['accept', 'accept', 'refuse', 'reject'] as const);
      evs.push({ t: 'answer', opt, how, late: rnd() < 0.2, newest: rnd() < 0.15 });
    } else if (withSecondButton && r < 0.86) evs.push({ t: 'press2' });
    else evs.push({ t: 'press' });
  }
  return evs;
}

// ── one run ──────────────────────────────────────────────────────────────────
type Req = {
  id: number; kind: 'save' | 'action'; key?: string; section?: string; value?: string; url: string;
  sentAt: number; ticket?: number; pressId?: number; done: boolean;
  resolve?: (r: any) => void; reject?: (e: any) => void;
  failedAt?: number;      // when the CLIENT knew it had not landed (refused, failed, or its deadline)
  failSeq?: number;
};
type Press = { id: number; button: number; start: number; startSeq: number; end?: number; nAhead: number; result?: string; actionSent: boolean };

const STATS: Record<string, number> = {};
const bump = (k: string) => { STATS[k] = (STATS[k] || 0) + 1; };

class Violation extends Error {
  constructor(public inv: string, msg: string) { super(`${inv}: ${msg}`); }
}

let LAST_TRACE: string[] = [];
async function runSeq(evs: Ev[], withSecondButton: boolean, opts: { liveness?: boolean } = {}): Promise<any> {
  const trace: string[] = [];
  LAST_TRACE = trace;
  const violations: Violation[] = [];
  const fail = (inv: string, msg: string) => { violations.push(new Violation(inv, msg)); };

  const server: Record<string, string> = {};
  for (const o of OPTS) server[`${o.section}.${o.name}`] = '0';
  const reqs: Req[] = [];
  const presses: Press[] = [];
  let autoAccept = false;
  let seq = 0;
  const typedSeq: Record<string, number> = {};
  // What the user last typed per option, and whether a late answer (after its deadline) has landed since.
  const typed: Record<string, string> = {};
  const lateSince: Record<string, boolean> = {};

  const panel: any = COMPONENTS.settingsPanel();
  const combined = { name: 'pass_key', type: 'combined', default: ',', combine: ['use', 'host', 'pass_key'], pairing: ['host', 'pass_key', 'use'] };
  const jkOptions: any[] = [{ name: 'url' }, { name: 'key' }, { name: 'extra' }, { name: 'sync', type: 'button', button_action: ACTION }];
  const groupCols = { use: '1', host: 'https://placeholder-one.invalid/api', pass_key: '' };
  if (WITH_GROUP) jkOptions.push({ name: 'use', default: '' }, { name: 'host', default: '' }, combined);
  panel.options = {
    jk: { name: 'jk', groups: [{ tab: 't', options: jkOptions }] },
    other: { name: 'other', groups: [{ tab: 't', options: [{ name: 'x' }] }] },
  };
  panel.values = { jk: { url: '0', key: '0', extra: '0', ...(WITH_GROUP ? groupCols : {}) }, other: { x: '0' } };
  panel.combineState = WITH_GROUP ? { jk: { misaligned: false, rows: 1 } } : {};
  panel.$nextTick = (cb: () => void) => cb();
  panel.$watch = () => {};
  if (WITH_GROUP) panel.ensureGroup(SECTION, combined);
  let rereads = 0;

  const buttons = [ACTION, ACTION2].map((action, i) => {
    const b: any = COMPONENTS.buttonField(SECTION, { button_action: action, name: `b${i}`, button_text: `B${i}` });
    b.getPanel = () => panel;
    return b;
  });

  // Instrumentation: which saveSingle calls a press queued (its batch), and when each link settled.
  type Rec = { key: string; value: string; ticket: number; batch: any; settled: boolean; pressId?: number };
  const recs: Rec[] = [];
  const batchPress = new WeakMap<object, number>();
  let currentPress: number | undefined;
  let sending: { key: string; ticket: number; pressId?: number } | undefined;
  const origSaveSingle = panel.saveSingle.bind(panel);
  panel.saveSingle = function (section: string, name: string, value: any, batch?: any) {
    const key = `${section}.${name}`;
    let pressId: number | undefined;
    if (batch) {
      if (!batchPress.has(batch) && currentPress !== undefined) batchPress.set(batch, currentPress);
      pressId = batchPress.get(batch);
      const lastOpen = recs.filter((r) => r.key === key && !r.settled).pop();
      if (lastOpen && String(lastOpen.value) === String(value)) {
        fail('I6', `press ${pressId} queued ${key}='${value}' while the last open save of it already carries '${lastOpen.value}'`);
      }
    }
    const link = origSaveSingle(section, name, value, batch);
    const rec: Rec = { key, value: String(value), ticket: panel.saveTickets[key], batch, settled: false, pressId };
    recs.push(rec);
    link.then(() => { rec.settled = true; });
    return link;
  };
  // A press's flush can run after an await (the combine group's flush), so the press is handed over in order.
  const flushQueue: number[] = [];
  const origFlushFor = panel.flushPendingSavesFor.bind(panel);
  panel.flushPendingSavesFor = function (section: string, captured?: any) {
    currentPress = flushQueue.shift();
    {
      const open = panel.openSavesOf(section);
      for (const entry of panel.unsavedOf(section)) {
        const mine = open.filter((l: any) => l.saveKey === entry.key);
        const last = mine[mine.length - 1];
        if (mine.some((l: any) => String(l.saveValue) === String(entry.value)) && !(last && String(last.saveValue) === String(entry.value))) bump('press: value equals an earlier open save but not the last (A,B,A)');
      }
    }
    try { return origFlushFor(section, captured); } finally { currentPress = undefined; }
  };
  const origSend = panel.sendSingleSave.bind(panel);
  panel.sendSingleSave = function (section: string, name: string, value: any, ticket: number) {
    const key = `${section}.${name}`;
    const rec = recs.find((r) => r.key === key && r.ticket === ticket);
    sending = { key, ticket, pressId: rec?.pressId };
    try { return origSend(section, name, value, ticket); } finally { sending = undefined; }
  };

  let nextId = 1;
  vi.stubGlobal('fetch', vi.fn((url: string, init?: any) => {
    const now = Date.now();
    if (/settings\.save\//.test(url)) {
      const p = new URLSearchParams(String(init.body));
      const key = `${p.get('section')}.${p.get('name')}`;
      const req: Req = {
        id: nextId++, kind: 'save', key, section: p.get('section')!, value: p.get('value')!, url,
        sentAt: now, ticket: sending?.ticket, pressId: sending?.pressId, done: false,
      };
      // I5: one at a time per section, unless every other open one is past its deadline.
      for (const r of reqs) {
        if (r.kind === 'save' && !r.done && r.section === req.section && now - r.sentAt < DEADLINE) {
          fail('I5', `save #${req.id} ${key}='${req.value}' sent while save #${r.id} ${r.key} is open and inside its deadline`);
        }
      }
      // I5: per option, sent in the order queued.
      const prev = reqs.filter((r) => r.kind === 'save' && r.key === key).pop();
      if (prev && req.ticket !== undefined && prev.ticket !== undefined && req.ticket <= prev.ticket) {
        fail('I5', `${key} ticket ${req.ticket} sent after ticket ${prev.ticket}`);
      }
      // I2: a save the press queued is not sent after a save of the section has not landed in that press.
      if (req.pressId !== undefined && req.section === SECTION) {
        const press = presses.find((x) => x.id === req.pressId)!;
        const bad = reqs.find((r) => r.kind === 'save' && r.section === SECTION && r.failedAt !== undefined
          && r.failSeq! > press.startSeq && r.failedAt <= now && r.sentAt < now);
        if (bad) fail('I2', `press ${press.id} sent ${key}='${req.value}' after save #${bad.id} ${bad.key}='${bad.value}' did not land`);
      }
      reqs.push(req);
      bump(req.pressId !== undefined ? 'save sent by a press' : 'save sent by debounce');
      if (reqs.some((r) => r !== req && r.kind === 'save' && !r.done && r.section === req.section)) bump('save sent with another of its section open (post-deadline)');
      trace.push(`    -> server receives save #${req.id} ${key}='${req.value}'${req.pressId !== undefined ? ` (queued by press ${req.pressId})` : ''}`);
      return new Promise((resolve, reject) => {
        req.resolve = resolve; req.reject = reject;
        if (autoAccept) answer(req, 'accept');
      });
    }
    if (/\/settings\/$/.test(url)) {
      rereads += 1;
      trace.push('    -> server receives the section re-read');
      const values: any = { jk: { ...groupCols }, other: {} };
      for (const [key, v] of Object.entries(server)) { const [sec, name] = key.split('.'); values[sec][name] = v; }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ values, combine_state: { jk: { misaligned: false, rows: 1 } }, options: panel.options }) });
    }
    // The action.
    const which = url.includes(ACTION2) ? 1 : 0;
    const pressRunning = presses.filter((x) => x.end === undefined && x.button === which);
    const req: Req = { id: nextId++, kind: 'action', url, sentAt: now, done: true };
    reqs.push(req);
    trace.push(`    -> server receives ACTION ${url.split('/').slice(-2)[0]}`);
    for (const press of pressRunning) press.actionSent = true;
    if (!autoAccept) bump('action sent');
    const pressStart = pressRunning.length ? pressRunning[0].startSeq : Infinity;
    // I1: every option of the section shows what the server accepted.
    for (const o of OPTS.filter((x) => x.section === SECTION)) {
      const key = `${o.section}.${o.name}`;
      const page = String(getVal({ dirty: panel.dirty, values: panel.values }, o.section, o.name));
      // Spec AC-PROD-12, limits that remain: a value typed after a press began is sent by the next press.
      if ((typedSeq[key] ?? -1) > pressStart) continue;
      if (key in typed && !lateSince[key] && typed[key] !== server[key]) {
        fail('I1', `action sent while the user last typed ${key}='${typed[key]}' and the server holds '${server[key]}'`);
      }
      if (page !== server[key]) fail('I1', `action sent while ${key} shows '${page}' and the server holds '${server[key]}'`);
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({ success: true, message: 'Synced' }) });
  }));

  function answer(req: Req, how: 'accept' | 'refuse' | 'reject') {
    req.done = true;
    const now = Date.now();
    const inDeadline = now - req.sentAt < DEADLINE;
    if (how === 'accept') {
      server[req.key!] = req.value!;
      if (!inDeadline) lateSince[req.key!] = true;
      req.resolve!({ ok: true, status: 200, json: async () => ({ success: true, value: req.value }) });
    } else if (how === 'refuse') {
      if (inDeadline) { req.failedAt = now; req.failSeq = ++seq; }
      req.resolve!({ ok: true, status: 200, json: async () => ({ success: false, error: 'no' }) });
    } else {
      if (inDeadline) { req.failedAt = now; req.failSeq = ++seq; }
      req.reject!(new TypeError('network'));
    }
    bump(`answer ${how}${inDeadline ? '' : ' late'}`);
    trace.push(`    <- save #${req.id} ${req.key}='${req.value}' answered ${how}${inDeadline ? '' : ' (after its deadline)'}; server now ${req.key}='${server[req.key!]}'`);
  }

  /** Mark every open save past its deadline as not landed, at the moment its deadline fell. */
  function markDeadlines() {
    const now = Date.now();
    for (const r of reqs) {
      if (r.kind === 'save' && !r.done && r.failedAt === undefined && now - r.sentAt >= DEADLINE) { r.failedAt = r.sentAt + DEADLINE; r.failSeq = ++seq; }
    }
  }

  async function advance(ms: number) {
    // In steps, so that deadlines are marked at most a step late relative to the sends they gate.
    let left = ms;
    while (left > 0) {
      const step = Math.min(left, 250);
      // Mark deadlines that fall inside this step before running its timers.
      const until = Date.now() + step;
      for (const r of reqs) {
        if (r.kind === 'save' && !r.done && r.failedAt === undefined && until - r.sentAt >= DEADLINE) { r.failedAt = r.sentAt + DEADLINE; r.failSeq = ++seq; }
      }
      await vi.advanceTimersByTimeAsync(step);
      left -= step;
    }
    markDeadlines();
  }

  function press(which: number) {
    const b = buttons[which];
    const id = presses.length + 1;
    if (b.busy) { bump('press while busy'); trace.push(`    (button ${which} busy: press ignored)`); return; }
    const nAhead = recs.filter((r) => r.key.startsWith(SECTION + '.') && !r.settled).length;
    const p: Press = { id, button: which, start: Date.now(), startSeq: ++seq, nAhead, actionSent: false };
    presses.push(p);
    flushQueue.push(id);
    const done = b.execute();
    done.then(() => {
      p.end = Date.now();
      p.result = b.result;
      if (!autoAccept) bump('press ended: ' + (/did not save/.test(b.result) ? 'refused text' : /not finished/.test(b.result) ? 'unanswered text' : b.result));
      trace.push(`    press ${id} ended: ${b.result}`);
    });
  }

  function checkAlways() {
    const now = Date.now();
    // I3
    for (const o of OPTS) {
      const key = `${o.section}.${o.name}`;
      const marked = key in panel.dirty || key in panel.pendingSaves;
      if (!marked) {
        const page = String(getVal({ dirty: panel.dirty, values: panel.values }, o.section, o.name));
        if (page !== server[key]) fail('I3', `${key} not marked unsaved, shows '${page}', server holds '${server[key]}'`);
        // The user's own last value is not lost: it is saved, or still marked (bar a recorded late overwrite).
        if (key in typed && !lateSince[key] && typed[key] !== server[key]) {
          fail('I3', `${key} not marked unsaved, the user last typed '${typed[key]}', the server holds '${server[key]}'`);
        }
      }
    }
    // I4: bound and justification.
    for (const p of presses) {
      const batchCount = recs.filter((r) => r.pressId === p.id).length;
      const bound = DEADLINE * (p.nAhead + batchCount) + 1000;
      if (p.end === undefined && now - p.start > bound) fail('I4', `press ${p.id} still running after ${now - p.start} ms (bound ${bound})`);
      if (p.end !== undefined && p.result !== undefined && !(p as any).judged) {
        (p as any).judged = true;
        // With two buttons a press can be held back by a save an overlapping press queued, and report what
        // stopped that one: its failure may precede this press's start, so the window is not bounded below.
        const inPress = reqs.filter((r) => r.kind === 'save' && r.section === SECTION && r.failedAt !== undefined
          && (withSecondButton || r.failSeq! > p.startSeq) && r.failedAt <= p.end!);
        if (/^Error/.test(p.result)) fail('I4', `press ${p.id} ended in an error: ${p.result}`);
        if (/did not save/.test(p.result) && !inPress.some((r) => r.failedAt! < r.sentAt + DEADLINE)) {
          fail('I4', `press ${p.id} said a change did not save, but no save of ${SECTION} was refused or failed in it`);
        }
        if (/not finished saving/.test(p.result) && inPress.length === 0) {
          fail('I4', `press ${p.id} said not finished saving, but no save of ${SECTION} reached its deadline in it`);
        }
        if (p.result === 'Synced' && !p.actionSent) fail('I4', `press ${p.id} says Synced and sent no action`);
      }
    }
  }

  const throwIfAny = () => { if (violations.length) throw violations[0]; };

  try {
    for (let i = 0; i < evs.length; i += 1) {
      const e = evs[i];
      trace.push(`${String(i + 1).padStart(2)}. ${show(e)}`);
      if (e.t === 'type') {
        const o = OPTS[e.opt];
        typedSeq[`${o.section}.${o.name}`] = ++seq;
        typed[`${o.section}.${o.name}`] = e.v;
        lateSince[`${o.section}.${o.name}`] = false;
        panel.setVal(o.section, o.name, e.v);
      } else if (e.t === 'tick') {
        await advance(e.ms);
      } else if (e.t === 'answer') {
        const key = `${OPTS[e.opt].section}.${OPTS[e.opt].name}`;
        const now = Date.now();
        const open = reqs.filter((r) => r.kind === 'save' && !r.done && r.key === key && (!e.late || now - r.sentAt >= DEADLINE));
        const req = e.newest ? open[open.length - 1] : open[0];
        if (req) answer(req, e.how); else trace.push('    (no such open save)');
      } else if (e.t === 'press') {
        press(0);
      } else if (e.t === 'press2') {
        if (withSecondButton) press(1);
      }
      await vi.advanceTimersByTimeAsync(0);
      markDeadlines();
      checkAlways();
      throwIfAny();
    }
    // Drain: let every press end. Unanswered saves stay unanswered.
    trace.push('-- drain: advance until every press ends');
    for (let k = 0; k < 40 && presses.some((p) => p.end === undefined); k += 1) {
      await advance(DEADLINE / 2);
      checkAlways();
      throwIfAny();
    }
    if (presses.some((p) => p.end === undefined)) fail('I4', 'a press never ended');
    if (opts.liveness === false) { throwIfAny(); return { trace, reqs, presses, panel, server }; }
    for (const b of buttons) if (b.running) fail('I4', 'a button is still running after every press ended');
    throwIfAny();
    // Liveness: with a server that accepts everything from now on, one press runs the action.
    trace.push('-- liveness: the server now accepts every save; press once');
    autoAccept = true;
    // Every open save's wait ends first: a request never answered is never answered.
    await advance(DEADLINE * 2 + DEBOUNCE + 1);
    const before = reqs.filter((r) => r.kind === 'action').length;
    press(0);
    for (let k = 0; k < 40 && presses.some((p) => p.end === undefined); k += 1) await advance(DEADLINE / 2);
    checkAlways();
    throwIfAny();
    const last = presses[presses.length - 1];
    if (last.result !== 'Synced' || reqs.filter((r) => r.kind === 'action').length !== before + 1) {
      fail('I4', `after the server accepts everything, a press ended '${last.result}' and sent ${reqs.filter((r) => r.kind === 'action').length - before} actions`);
    }
    for (const o of OPTS.filter((x) => x.section === SECTION)) {
      const key = `${o.section}.${o.name}`;
      if (key in panel.dirty) fail('I3', `after a landed press ${key} is still marked unsaved ('${panel.dirty[key]}', server '${server[key]}')`);
    }
    throwIfAny();
  } finally {
    vi.clearAllTimers();
  }
  return { trace, reqs, presses, panel, server };
}

async function runFresh(evs: Ev[], withSecondButton: boolean) {
  vi.useRealTimers();
  vi.useFakeTimers();
  vi.setSystemTime(0);
  try {
    await runSeq(evs, withSecondButton);
    return null;
  } catch (e: any) {
    if (e instanceof Violation) return e;
    return new Violation('CRASH', String(e && e.stack || e));
  }
}

/** Delta-debugging style shrink: drop chunks, then single events, keeping the same invariant failing. */
async function shrink(evs: Ev[], inv: string, withSecondButton: boolean): Promise<Ev[]> {
  let cur = evs;
  let chunk = Math.max(1, Math.floor(cur.length / 2));
  while (chunk >= 1) {
    let changed = false;
    for (let i = 0; i + chunk <= cur.length;) {
      const cand = [...cur.slice(0, i), ...cur.slice(i + chunk)];
      const v = await runFresh(cand, withSecondButton);
      if (v && v.inv === inv) { cur = cand; changed = true; } else i += 1;
    }
    if (!changed) chunk = Math.floor(chunk / 2);
  }
  // Simplify ticks.
  for (let i = 0; i < cur.length; i += 1) {
    const e = cur[i];
    if (e.t === 'tick') {
      for (const ms of [DEBOUNCE, DEADLINE]) {
        if (ms >= e.ms) continue;
        const cand = [...cur.slice(0, i), { t: 'tick', ms } as Ev, ...cur.slice(i + 1)];
        const v = await runFresh(cand, withSecondButton);
        if (v && v.inv === inv) { cur = cand; break; }
      }
    }
  }
  return cur;
}

async function report(seed: number, evs: Ev[], v: Violation, withSecondButton: boolean) {
  const small = await shrink(evs, v.inv, withSecondButton);
  vi.useRealTimers();
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let trace: string[] = [];
  let msg = '';
  try { trace = (await runSeq(small, withSecondButton)).trace; } catch (e: any) { msg = e.message; trace = LAST_TRACE; }
  // Re-run once more to capture the trace up to the failure.
  vi.useRealTimers(); vi.useFakeTimers(); vi.setSystemTime(0);
  return `seed ${seed}${withSecondButton ? ' (two buttons)' : ''}: ${v.inv} broke\n  minimal script (${small.length} events):\n${small.map((e, i) => `    ${i + 1}. ${show(e)}`).join('\n')}\n  failure: ${msg || v.message}\n  trace:\n${trace.map((l) => '      ' + l).join('\n')}`;
}

const RUNS = Number(process.env.MODEL_RUNS || 100);
const BASE = Number(process.env.MODEL_SEED || 1);
const ONLY_TWO = process.env.MODEL_TWO_BUTTONS === '1';
const ONLY_GROUP = process.env.MODEL_GROUP;
// The two-button run in the default file: fixed seeds that include the one that found the held-back press
// reporting the wrong text (seed 102327).
const TWO_BUTTON_DEFAULT = { base: 102320, runs: 30 };

beforeEach(() => {
  vi.stubGlobal('CP', {
    apiBase: '/api/placeholder-api-key',
    ui: { getVal, isEnabledValue: (v: unknown) => v === true || v === '1', buildDescription: () => '' },
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function soak(label: string, base: number, runs: number, two: boolean, group: boolean) {
  WITH_GROUP = group;
  const failures: string[] = [];
  const seen = new Set<string>();
  for (let s = base; s < base + runs; s += 1) {
    const evs = genSeq(s, two);
    const v = await runFresh(evs, two);
    if (v) {
      if (seen.has(v.inv) && failures.length >= 6) continue;
      seen.add(v.inv);
      failures.push(await report(s, evs, v, two));
      if (failures.length >= 8) break;
    }
  }
  if (process.env.MODEL_STATS) fs.writeFileSync(process.env.MODEL_STATS, JSON.stringify(STATS, null, 1));
  if (failures.length) console.log(`${label}\n${failures.join('\n\n')}`);
  expect(failures).toEqual([]);
}

describe('SEC-005 D7 single-option save bookkeeping, against a model', () => {
  const shapes: Array<[string, boolean]> = [['a plain section', false], ['a section with a combine group', true]];
  for (const [name, group] of shapes) {
    if (ONLY_TWO || (ONLY_GROUP !== undefined && ONLY_GROUP !== '' && (ONLY_GROUP === '1') !== group)) continue;
    it(`holds I1 to I6 over ${RUNS} seeded sequences from seed ${BASE}: ${name}, one button`, async () => {
      await soak(name, BASE, RUNS, false, group);
    }, 3_600_000);
  }

  it(`holds I1 to I6 with two buttons in one section and overlapping presses${ONLY_TWO ? `: ${RUNS} sequences from seed ${BASE}` : ': a short fixed run'}`, async () => {
    const [base, runs] = ONLY_TWO ? [BASE, RUNS] : [TWO_BUTTON_DEFAULT.base, TWO_BUTTON_DEFAULT.runs];
    await soak('two buttons', base, runs, true, ONLY_GROUP === '1');
  }, 3_600_000);
});

// ── hand-written sequences: the four earlier defects, and the late answer the fuzzer only samples ──
describe('SEC-005 D7 the earlier defects, as scripted sequences through the same model', () => {
  const T = (opt: number, v: string): Ev => ({ t: 'type', opt, v });
  const tick = (ms: number): Ev => ({ t: 'tick', ms });
  const ans = (opt: number, how: 'accept' | 'refuse' | 'reject', late = false): Ev => ({ t: 'answer', opt, how, late });
  const press: Ev = { t: 'press' };
  const URL_ = 0;
  const KEY = 1;

  async function scripted(evs: Ev[]) {
    WITH_GROUP = false;
    vi.useRealTimers();
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const out = await runSeq(evs, false, { liveness: false });
    return out;
  }
  const sent = (out: any) => out.reqs.filter((r: any) => r.kind === 'save').map((r: any) => `${r.key.split('.')[1]}=${r.value}`);
  const actions = (out: any) => out.reqs.filter((r: any) => r.kind === 'action').length;

  it('1: address refused and answered, then the key typed, then a press: the address is sent again, the key is not, no action', async () => {
    const out = await scripted([T(URL_, 'a'), tick(500), ans(URL_, 'refuse'), T(KEY, 'b'), press, ans(URL_, 'refuse')]);
    expect(sent(out)).toEqual(['url=a', 'url=a']);
    expect(actions(out)).toBe(0);
    expect(out.presses[0].result).toMatch(/did not save/);
    expect(out.panel.dirty).toEqual({ 'jk.url': 'a', 'jk.key': 'b' });
  });

  it('2: a stopped press does not save the key behind the refused address, even once the address times out instead', async () => {
    const out = await scripted([T(URL_, 'a'), T(KEY, 'b'), press, tick(10_000), tick(10_000)]);
    expect(sent(out)).toEqual(['url=a']);
    expect(out.presses[0].result).toMatch(/not finished saving/);
    expect(out.server['jk.key']).toBe('0');
  });

  it('3: a second press re-sends the refused address first, then the key, then runs the action', async () => {
    const out = await scripted([T(URL_, 'a'), T(KEY, 'b'), press, ans(URL_, 'refuse'), press, ans(URL_, 'accept'), ans(KEY, 'accept')]);
    expect(sent(out)).toEqual(['url=a', 'url=a', 'key=b']);
    expect(actions(out)).toBe(1);
    expect(out.panel.dirty).toEqual({});
  });

  it('4: A in flight, B queued, A typed again, press: A, B, A are sent and the action runs on A', async () => {
    const out = await scripted([T(URL_, 'a'), tick(500), T(URL_, 'b'), tick(500), T(URL_, 'a'), press,
      ans(URL_, 'accept'), ans(URL_, 'accept'), ans(URL_, 'accept')]);
    expect(sent(out)).toEqual(['url=a', 'url=b', 'url=a']);
    expect(actions(out)).toBe(1);
    expect(out.server['jk.url']).toBe('a');
  });

  it('5: as 4 with the final A refused: no action, A stays unsaved, and the next press sends A and runs', async () => {
    const out = await scripted([T(URL_, 'a'), tick(500), T(URL_, 'b'), tick(500), T(URL_, 'a'), press,
      ans(URL_, 'accept'), ans(URL_, 'accept'), ans(URL_, 'refuse'), press, ans(URL_, 'accept')]);
    expect(sent(out)).toEqual(['url=a', 'url=b', 'url=a', 'url=a']);
    expect(out.presses[0].result).toMatch(/did not save/);
    expect(actions(out)).toBe(1);
    expect(out.server['jk.url']).toBe('a');
  });

  it('6 (late answer, recorded limit): an address unanswered past its deadline that lands after a newer one overwrites it, and the page shows the server, not the typed value', async () => {
    const out = await scripted([T(URL_, 'a'), tick(500), tick(10_000), T(URL_, 'b'), tick(500),
      { t: 'answer', opt: URL_, how: 'accept', newest: true }, ans(URL_, 'accept', true)]);
    expect(sent(out)).toEqual(['url=a', 'url=b']);
    // The server ends on the stale a; the field shows a too (it shows what the server returned), and b is not marked.
    expect(out.server['jk.url']).toBe('a');
    expect(String(out.panel.getVal('jk', 'url'))).toBe('a');
    expect(out.panel.dirty).toEqual({});
  });
});
