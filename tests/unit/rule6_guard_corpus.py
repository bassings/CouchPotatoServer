"""Rule 6's guard-spelling corpus: every shape, scored in one place.

Spec gap 23. This rule regressed in FIVE consecutive review rounds, every time
on a formatting shape rather than on its meaning, and every time the fix was
validated by adding one ad-hoc test for the shape that round happened to
notice. So the sixth edit was scored against the fifth bug.

A table is the fix. Any change to the routing or the body slice is now scored
against all of these at once, which is what surfaced shape 23 -- a false
positive no individual test could see.

Wrong-answer counts measured against this table, so a future edit can tell
improvement from drift. Each is a real spelling this rule shipped at some
point in review rounds 3 to 7:

    shipped (LAST block opener on the line)   0 / 25
    first block opener on the line            1 / 25   <- shape 23
    line.index("{")                           3 / 25
    line.rfind("{")                           3 / 25
    gated on `not opens_block`                5 / 25
    no inline slice at all                   16 / 25

Shapes with an expected count of 0 are as important as the 1s: a rule whose
documented remedy for a false positive is an opt-out comment teaches people to
silence it, which is worse than the vacuity it was written to catch.
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

 ("20 multi-line condition (documented blind spot)", T +
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
]
