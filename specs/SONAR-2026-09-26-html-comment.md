# SONAR: prevent an HTML-language false positive in CSS comments

The exact-master scan at `d014739cdb36ed8706b458f6ffd3b732a2ad6e49`
reported one reliability bug: `Web:S5254`, issue
`0033d130-cfb9-4792-98a3-02f0d269b4cb`, at
`couchpotato/ui/templates/base.html:211`. That line is a CSS comment
mentioning an opening HTML tag. The actual root element at line 2 declares
`lang="en"`.

## Acceptance criteria

- A browser test proves the rendered shared page has
  `document.documentElement.lang === 'en'`.
- A focused guard inspects the `base.html` template source, not just rendered
  output, and rejects an opening HTML tag token inside its CSS comments,
  including a token hidden in a Jinja branch that never renders. Prove the
  guard is load-bearing by applying and restoring an equivalent mutation.
- Change only the misleading CSS-comment wording in production. Preserve the
  theme explanation, rendered markup, styles and behaviour.
- Focused tests, the full repository gate and two independent local code
  reviews pass before pushing.
- After merge, a fresh clean exact-master Sonar analysis completes and reports
  zero open reliability bugs with an A reliability rating. Do not mark or
  dismiss the issue merely to improve the rating.
