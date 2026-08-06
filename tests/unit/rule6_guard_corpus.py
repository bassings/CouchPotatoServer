"""Rule 6's guard-spelling corpus: every shape, scored in one place.

Spec gap 23. This rule regressed in FIVE consecutive review rounds, every time
on a formatting shape rather than on its meaning, and every time the fix was
validated by adding one ad-hoc test for the shape that round happened to
notice. So the sixth edit was scored against the fifth bug.

A table is the fix. Any change to the routing or the body slice is now scored
against all of these at once, which is what surfaced shape 23 -- a false
positive no individual test could see.

Wrong-answer counts, RE-DERIVED at round 10 against all 32 shapes by scoring
this table against the actual historical files from git
(`git show <sha>:scripts/check_test_traps.py`) and against one-line variants
of the shipped file. Reproduce, do not trust:

    shipped                                    0 / 32
    4a8e9d00  round 6, first `){`              3 / 32   shapes 23, 31, 32
    d9c70c83  round 7, last `){`               5 / 32   shapes 26-28, 31, 32
    dc4fdab5  round 4                          4 / 32   shapes 07, 23, 31, 32
    65ca81f7  round 5                          7 / 32   shapes 03, 19, 24, 25, 27, 31, 32
    eada3f1b  round 3                         17 / 32
    cd180e05  round 2                         17 / 32
    9c11c598  original                        18 / 32

    one-line variants of the shipped file:
      take the LAST `){` instead of the first   3 / 32   shapes 26-28
      skip the string blanking                  1 / 32   shape 23
      drop the `opens_block or inline_block`
        routing gate (`if True:`)               1 / 32   shape 16

THE DENOMINATOR IS PART OF THE MEASUREMENT. The previous table read `/ 30`,
because it was scored when the corpus held 30 shapes and shapes 31-32 were
added in the same commit. Every historical row therefore UNDERSTATED, and one
of them understated in a way that falsified the table's own conclusion: the
text asserted "no version this rule ever shipped scores worse than 17", while
the original scores 18. Re-score the whole table when you add a shape; do not
append a row.

The round-8 table this replaces was itself a correction of a round-7 one that
recorded 3/3/5/16. Those came from applying reconstructed slice spellings to
the CURRENT file, producing hybrids that never shipped. Two corrections in
three rounds, on a table whose entire purpose is to be trustworthy, is the
argument for scoring it mechanically: the numbers above were produced by a
script that loads each `git show` output as a module and asserts
`hasattr(m, "check_file")` first -- because a zsh history-expansion bug once
turned `git show "$c:scripts/..."` into an empty file, and an empty module
scores every shape wrong, which looks exactly like a catastrophically bad
historical version.

If you change this table, score against `git show`, not against a
reconstruction.

Shapes with an expected count of 0 are as important as the 1s: a rule whose
documented remedy for a false positive is an opt-out comment teaches people to
silence it, which is worse than the vacuity it was written to catch.

Two kinds of expected-0 live here and they are NOT the same. Most are correct
silence. Shape 20 is a known BLIND SPOT, named as such: it is a genuinely
vacuous guard the rule cannot see. If a future change makes shape 20 report 1,
that is GOOD NEWS and the table should be updated -- not a regression to
revert. Any shape whose name says BLIND SPOT carries that contract.
"""

# Every shape is a whole spec file, so the checker sees what it sees in the
# repo: `T` opens a test, `E` closes it.
T = "test('t', async ({ page }) => {\n"
E = "});\n"

SHAPES = [
 ("01 classic multi-line braced guard, expect inside", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) {\n"
  "    await expect(c).toBeVisible();\n"
  "  }\n" + E, 1),

 ("02 one-line guard, expect inside braces", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); }\n" + E, 1),

 ("03 braced guard, expect on guard line, closes later", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible();\n"
  "    await c.click();\n"
  "  }\n" + E, 1),

 ("04 same shape written `} else if`", T +
  "  const c = page.locator('.card');\n"
  "  if (false) {\n"
  "  } else if (await c.count() > 0) { await expect(c).toBeVisible();\n"
  "    await c.click();\n"
  "  }\n" + E, 1),

 ("05 non-braced early return, expect after", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() === 0) return;\n"
  "  await expect(c).toBeVisible();\n" + E, 1),

 ("06 template-literal brace in condition, body asserts nothing", T +
  "  if (await page.locator(`#movie-${id}`).count() > 0) {\n"
  "    await page.click('.go');\n"
  "  }\n"
  "  await page.waitForTimeout(1);\n" + E, 0),

 ("07 condition string mentions expect(, body asserts nothing", T +
  "  if (await page.getByText('{0} expect(x)').count() > 0) { await page.click('.go'); }\n"
  "  await page.waitForTimeout(1);\n" + E, 0),

 ("08 one-liner: expect BEFORE a nested object literal", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toHaveScreenshot({ maxDiffPixels: 3 }); }\n" + E, 1),

 ("09 hoisted count, multi-line braced, expect inside", T +
  "  const total = await page.locator('.card').count();\n"
  "  if (total > 1) {\n"
  "    await expect(page.locator('.card').first()).toBeVisible();\n"
  "  }\n" + E, 1),

 ("10 hoisted count, one-line", T +
  "  const total = await page.locator('.card').count();\n"
  "  if (total > 1) { await expect(page.locator('.card').first()).toBeVisible(); }\n" + E, 1),

 ("11 opt-out with a reason", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); } // vacuous-guard-ok: seeded upstream\n" + E, 0),

 ("12 opt-out with an empty reason", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); } // vacuous-guard-ok:\n" + E, 1),

 ("13 click-only guard, no expect anywhere (out of scope by design)", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) {\n"
  "    await c.click();\n"
  "  }\n" + E, 0),

 ("14 one-liner whose condition carries filter({...}), expect on the line", T +
  "  const rows = page.locator('tr');\n"
  "  if (await rows.filter({ hasText: 'x' }).count() > 0) { await expect(rows.first()).toBeVisible(); }\n" + E, 1),

 ("15 filter({...}) condition, multi-line body with expect", T +
  "  const rows = page.locator('tr');\n"
  "  if (await rows.filter({ hasText: 'x' }).count() > 0) {\n"
  "    await expect(rows.first()).toBeVisible();\n"
  "  }\n" + E, 1),

 ("16 non-braced teardown guard; expect only in a LATER test", 
  "test('teardown', async ({ page }) => {\n"
  "  const del = page.locator('.del');\n"
  "  if (await del.count() === 0) return;\n"
  "  await del.click();\n"
  "});\n"
  "test('other', async ({ page }) => {\n"
  "  await expect(page.locator('.x')).toBeVisible();\n"
  "});\n", 0),

 ("17 ordinary non-guard if, expect inside", T +
  "  if (process.env.CI) {\n"
  "    await expect(page.locator('.x')).toBeVisible();\n"
  "  }\n" + E, 0),

 ("18 one-liner with trailing statement after the closing brace", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); } else { await c.click(); }\n" + E, 1),

 ("19 selector string containing braces, expect on guard line, closes later", T +
  "  const c = page.locator('[data-tpl=\"{a}\"]');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible();\n"
  "    await c.click();\n"
  "  }\n" + E, 1),

 ("20 multi-line condition (BLIND SPOT: expected 0 until fixed)", T +
  "  const c = page.locator('.card');\n"
  "  if (\n"
  "    await c.count() > 0\n"
  "  ) {\n"
  "    await expect(c).toBeVisible();\n"
  "  }\n" + E, 0),

 ("21 template literal mentioning expect( in condition, real expect in body", T +
  "  if (await page.getByText(`{x} expect(y)`).count() > 0) {\n"
  "    await expect(page.locator('.z')).toBeVisible();\n"
  "  }\n" + E, 1),

 ("22 `} else if` one-liner with expect", T +
  "  const c = page.locator('.card');\n"
  "  if (false) {\n"
  "  } else if (await c.count() > 0) { await expect(c).toBeVisible(); }\n" + E, 1),

 ("23 condition string literally containing `){`, body asserts nothing", T +
  "  if (await page.getByText('a ){ b expect(q)').count() > 0) { await page.click('.go'); }\n"
  "  await page.waitForTimeout(1);\n" + E, 0),

 ("24 guard line ending in `{` with expect on the SAME line after a nested obj", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { const o = { a: 1 }; await expect(c).toBeVisible();\n"
  "    await c.click();\n"
  "  }\n" + E, 1),

 ("25 expect on guard line; body's later line has an object literal", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible();\n"
  "    await c.screenshot({ path: 'x.png' });\n"
  "  }\n" + E, 1),

 # --- added at review round 8 -------------------------------------------
 # 26-29: a NESTED block opener after the assertion on the guard line. The
 # "take the last `){`" spelling went silent on all four; none of the 25
 # shapes above could see it, so the table scored 0/25 on the round that
 # introduced the regression.
 ("26 nested if on the guard line, expect before it, one-liner", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); if (1 > 0) { await c.click(); } }\n" + E, 1),

 ("27 nested if on the guard line, block closes later", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); if (1 > 0) {\n"
  "      await c.click();\n"
  "    }\n"
  "  }\n" + E, 1),

 ("28 for-loop opener on the guard line after the expect", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); for (let i = 0; i < 2; i++) { await c.click(); } }\n" + E, 1),

 # 29-30: the rule's PRIMARY false-positive risk and its own recommended
 # remedy. Forcing the routing to always use the enclosing-block scan scored
 # 0/25 on the original table, so the corpus did not cover the routing at all
 # despite claiming to.
 ("29 one-line click-only guard, unconditional expect on the NEXT line", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await c.click(); }\n"
  "  await expect(page.locator('h1')).toBeVisible();\n" + E, 0),

 ("30 braced click-only guard, expect after the closing brace", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) {\n"
  "    await c.click();\n"
  "  }\n"
  "  await expect(page.locator('h1')).toBeVisible();\n" + E, 0),

 # 31-32: the rule's OWN recommended remedy. Its message says "assert both
 # branches if it is not", and it used to flag exactly that, so two live
 # opt-outs in this suite existed only to silence the rule for complying.
 ("31 both branches assert, one-liner", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) { await expect(c).toBeVisible(); } else { await expect(c).toHaveCount(0); }\n" + E, 0),

 ("32 both branches assert, multi-line", T +
  "  const c = page.locator('.card');\n"
  "  if (await c.count() > 0) {\n"
  "    await expect(c).toBeVisible();\n"
  "  } else {\n"
  "    await expect(c).toHaveCount(0);\n"
  "  }\n" + E, 0),
]
