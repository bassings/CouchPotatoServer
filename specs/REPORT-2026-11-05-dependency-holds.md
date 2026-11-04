# Installed npm dependency holds, 5 November 2026

Measured with npm outdated --all and Arborist loadActual after the refresh.
Each row is an actual installed location; absent optional peers/platform binaries
are excluded. Shared installations must satisfy every parent. Raw upstream
constraints are shown, with effective overrides labelled.

| Package | Installed | Latest | Retaining constraint or decision |
| --- | --- | --- | --- |
| @babel/core | 8.0.10 | 8.1.0 | @babel/helper-create-class-features-plugin 8.0.10: ^8.0.0; @babel/helper-module-transforms 8.1.0: ^8.0.0; @babel/helper-plugin-utils 8.0.1: ^8.0.0; @babel/helper-replace-supers 8.0.1: ^8.0.0; @babel/plugin-proposal-decorators 8.0.2: ^8.0.0; @babel/plugin-syntax-decorators 8.0.1: ^8.0.0; @babel/plugin-syntax-jsx 8.0.1: ^8.0.0; @babel/plugin-syntax-typescript 8.0.3: ^8.0.0; @babel/plugin-transform-destructuring 8.0.5: ^8.0.0; @babel/plugin-transform-explicit-resource-management 8.0.5: ^8.0.0; @babel/plugin-transform-modules-commonjs 8.0.1: ^8.0.0; @babel/plugin-transform-react-display-name 8.0.1: ^8.0.0; @babel/plugin-transform-react-jsx 8.0.1: ^8.0.0; @babel/plugin-transform-react-jsx-development 8.0.1: ^8.0.0; @babel/plugin-transform-react-pure-annotations 8.0.1: ^8.0.0; @babel/plugin-transform-typescript 8.0.6: ^8.0.0; @babel/preset-react 8.0.1: ^8.0.0; @babel/preset-typescript 8.0.7: ^8.0.0; @stryker-mutator/instrumenter 10.1.1: ~8.0.0 |
| @babel/generator | 8.0.10 | 8.1.0 | @babel/core 8.0.10: ^8.0.10; @babel/traverse 8.0.10: ^8.0.10; @stryker-mutator/instrumenter 10.1.1: ~8.0.0 |
| @babel/helper-string-parser | 7.29.13 | 8.0.8 | @babel/types 7.29.11: ^7.29.11 |
| @babel/helper-validator-identifier | 7.29.7 | 8.0.6 | @babel/types 7.29.11: ^7.29.7 |
| @babel/parser | 8.0.10 | 8.1.0 | @babel/core 8.0.10: ^8.0.10; @babel/generator 8.0.10: ^8.0.10; @babel/template 8.0.0: ^8.0.0; @babel/traverse 8.0.10: ^8.0.10; @stryker-mutator/instrumenter 10.1.1: ~8.0.0 |
| @babel/parser | 7.29.13 | 8.1.0 | magicast 0.5.5: ^7.29.7 |
| @babel/traverse | 8.0.10 | 8.1.0 | @babel/core 8.0.10: ^8.0.10; @babel/helper-create-class-features-plugin 8.0.10: ^8.0.10; @babel/helper-member-expression-to-functions 8.0.5: ^8.0.5; @babel/helper-module-imports 8.0.0: ^8.0.0; @babel/helper-replace-supers 8.0.1: ^8.0.0; @stryker-mutator/instrumenter 10.1.1: ~8.0.4 |
| @babel/types | 7.29.11 | 8.1.0 | magicast 0.5.5: ^7.29.7; @babel/parser 7.29.13: ^7.29.11 |
| @formatjs/ecma402-abstract | 2.3.6 | 3.2.0 | @formatjs/icu-messageformat-parser 2.11.4: 2.3.6; @formatjs/icu-skeleton-parser 1.8.16: 2.3.6; intl-messageformat 10.7.18: 2.3.6 |
| @formatjs/fast-memoize | 2.2.7 | 3.1.7 | @formatjs/ecma402-abstract 2.3.6: 2.2.7; intl-messageformat 10.7.18: 2.2.7 |
| @formatjs/icu-messageformat-parser | 2.11.4 | 3.5.22 | intl-messageformat 10.7.18: 2.11.4 |
| @formatjs/icu-skeleton-parser | 1.8.16 | 2.1.12 | @formatjs/icu-messageformat-parser 2.11.4: 1.8.16 |
| @formatjs/intl-localematcher | 0.6.2 | 0.10.1 | @formatjs/ecma402-abstract 2.3.6: 0.6.2 |
| @jridgewell/gen-mapping | 0.4.0-beta.0 | 0.3.13 | Latest tag is older than installed |
| @opentelemetry/api | 1.9.1 | 1.10.0 | @opentelemetry/api-logs 0.220.0: ^1.3.0; @opentelemetry/core 2.12.0: >=1.0.0 <1.10.0; @opentelemetry/instrumentation 0.220.0: ^1.3.0; @opentelemetry/resources 2.12.0: >=1.3.0 <1.10.0; @opentelemetry/sdk-trace 2.12.0: >=1.3.0 <1.10.0; @opentelemetry/sdk-trace-base 2.12.0: >=1.3.0 <1.10.0; @sentry/node 10.78.0: >=1.9.1 <1.10.0; @sentry/node-core 10.78.0: >=1.9.0 <1.10.0; @sentry/opentelemetry 10.78.0: >=1.9.0 <1.10.0; vitest 5.1.0: ^1.9.0 |
| @opentelemetry/api-logs | 0.220.0 | 0.223.0 | @opentelemetry/instrumentation 0.220.0: 0.220.0 |
| @opentelemetry/core | 2.12.0 | 3.0.0 | @opentelemetry/resources 2.12.0: 2.12.0; @opentelemetry/sdk-trace 2.12.0: 2.12.0; @opentelemetry/sdk-trace-base 2.12.0: 2.12.0; @sentry/node-core 10.78.0: ^1.30.1 \|\| ^2.1.0; @sentry/opentelemetry 10.78.0: ^1.30.1 \|\| ^2.1.0 |
| @opentelemetry/instrumentation | 0.220.0 | 0.300.0 | @sentry/node 10.78.0: ^0.220.0; @sentry/node-core 10.78.0: >=0.57.1 <0.300.0 |
| @opentelemetry/resources | 2.12.0 | 3.0.0 | @opentelemetry/sdk-trace 2.12.0: 2.12.0; @opentelemetry/sdk-trace-base 2.12.0: 2.12.0 |
| @opentelemetry/sdk-trace | 2.12.0 | 3.0.0 | @opentelemetry/sdk-trace-base 2.12.0: 2.12.0 |
| @oxc-project/types | 0.156.0 | 0.157.0 | rolldown 1.2.16: =0.156.0 |
| @paulirish/trace_engine | 0.0.65 | 0.0.68 | lighthouse 13.5.0: 0.0.65 |
| @sec-ant/readable-stream | 0.4.1 | 0.7.1 | get-stream 9.0.1: ^0.4.1 |
| @sentry/conventions | 0.16.0 | 0.30.0 | @sentry/core 10.78.0: ^0.16.0; @sentry/node 10.78.0: ^0.16.0; @sentry/node-core 10.78.0: ^0.16.0; @sentry/opentelemetry 10.78.0: ^0.16.0; @sentry/server-utils 10.78.0: ^0.16.0 |
| @sentry/core | 10.78.0 | 11.10.0 | @sentry/node 10.78.0: 10.78.0; @sentry/node-core 10.78.0: 10.78.0; @sentry/opentelemetry 10.78.0: 10.78.0; @sentry/server-utils 10.78.0: 10.78.0 |
| @sentry/node | 10.78.0 | 11.10.0 | lighthouse 13.5.0: ^10.0.0 |
| @sentry/node-core | 10.78.0 | 10.75.2 | Latest tag is older than installed |
| @sentry/opentelemetry | 10.78.0 | 11.10.0 | @sentry/node 10.78.0: 10.78.0; @sentry/node-core 10.78.0: 10.78.0 |
| @sentry/server-utils | 10.78.0 | 11.10.0 | @sentry/node 10.78.0: 10.78.0 |
| @types/jsesc | 2.5.1 | 3.0.3 | @babel/generator 8.0.10: ^2.5.0; @babel/generator 8.1.0: ^2.5.0; @babel/generator 8.1.0: ^2.5.0 |
| angular-html-parser | 10.11.0 | 10.13.0 | @stryker-mutator/instrumenter 10.1.1: ~10.11.0 |
| ansi-regex | 5.0.1 | 6.5.0 | strip-ansi 6.0.1: ^5.0.1 |
| ansi-styles | 6.2.3 | 7.0.0 | wrap-ansi 9.0.2: ^6.2.1 |
| ansi-styles | 4.3.0 | 7.0.0 | wrap-ansi 7.0.0: ^4.0.0 |
| balanced-match | 4.0.4 | 5.0.0 | brace-expansion 5.0.12: ^4.0.2 |
| chalk | 5.6.2 | 6.0.1 | @stryker-mutator/core 10.1.1: ~5.6.0 |
| chromium-bidi | 157.0.8090-0 | 159.0.8143-0 | puppeteer-core 25.16.0: 157.0.8090-0 |
| cliui | 8.0.1 | 9.0.1 | yargs 17.7.3: ^8.0.1 |
| color-convert | 2.0.1 | 3.1.3 | ansi-styles 4.3.0: ^2.0.1 |
| color-name | 1.1.4 | 2.1.1 | color-convert 2.0.1: ~1.1.4 |
| commander | 14.0.3 | 15.0.0 | @stryker-mutator/core 10.1.1: ~14.0.0 |
| configstore | 7.1.0 | 8.0.0 | lighthouse 13.5.0: ^7.0.0 |
| define-lazy-prop | 2.0.0 | 3.0.0 | open 8.4.2: ^2.0.0 |
| devtools-protocol | 0.0.1687809 | 0.0.1734725 | chromium-bidi 157.0.8090-0: *; lighthouse 13.5.0: 0.0.1687809 |
| devtools-protocol | 0.0.1704951 | 0.0.1734725 | puppeteer-core 25.16.0: 0.0.1704951 |
| dot-prop | 9.0.0 | 10.2.0 | configstore 7.1.0: ^9.0.0 |
| emoji-regex | 10.6.0 | 11.0.0 | string-width 7.2.0: ^10.3.0; string-width 7.2.0: ^10.3.0; @stryker-mutator/core 10.1.1: ~10.6.0 |
| emoji-regex | 8.0.0 | 11.0.0 | string-width 4.2.3: ^8.0.0 |
| es-module-lexer | 2.3.2 | 3.0.4 | vitest 5.1.0: ^2.3.2 |
| escape-string-regexp | 4.0.0 | 5.0.0 | chrome-launcher 1.2.2: ^4.0.0 |
| execa | 9.6.1 | 10.2.1 | @stryker-mutator/core 10.1.1: ~9.6.0 |
| fast-uri | 3.1.9 | 4.2.3 | ajv 8.20.0: ^3.0.1 |
| intl-messageformat | 10.7.18 | 12.1.4 | lighthouse 13.5.0: ^10.5.3 |
| is-docker | 2.2.1 | 4.0.0 | is-wsl 2.2.0: ^2.0.0; open 8.4.2: ^2.1.1 |
| is-fullwidth-code-point | 3.0.0 | 5.1.0 | string-width 4.2.3: ^3.0.0 |
| is-wsl | 2.2.0 | 3.1.1 | chrome-launcher 1.2.2: ^2.2.0; open 8.4.2: ^2.2.0 |
| isexe | 2.0.0 | 4.0.0 | which 2.0.2: ^2.0.0 |
| lighthouse | 13.5.0 | 13.6.0 | Hold 13.6.0: fresh audit finds vulnerable glob/minimatch via Sentry 11 |
| mdn-data | 2.27.1 | 2.37.2 | css-tree 3.2.1: 2.27.1 |
| mutation-testing-elements | 3.8.4 | 3.9.0 | @stryker-mutator/core 10.1.1: 3.8.4 |
| mutation-testing-metrics | 3.8.4 | 3.9.0 | @stryker-mutator/api 10.1.1: 3.8.4; @stryker-mutator/core 10.1.1: 3.8.4 |
| mutation-testing-report-schema | 3.8.4 | 3.9.0 | @stryker-mutator/api 10.1.1: 3.8.4; @stryker-mutator/core 10.1.1: 3.8.4; mutation-testing-metrics 3.8.4: 3.8.4 |
| mute-stream | 3.0.0 | 4.0.0 | @inquirer/core 12.0.6: ^3.0.0 |
| nanoid | 3.3.20 | 6.0.2 | postcss 8.5.32: ^3.3.20 |
| open | 8.4.2 | 11.0.4 | lighthouse 13.5.0: ^8.4.0 |
| parse-ms | 4.0.0 | 5.0.0 | pretty-ms 9.3.1: ^4.0.0 |
| path-key | 3.1.1 | 4.0.0 | cross-spawn 7.0.6: ^3.1.0 |
| pretty-ms | 9.3.1 | 10.0.0 | execa 9.6.1: ^9.2.0 |
| shebang-regex | 3.0.0 | 4.0.0 | shebang-command 2.0.0: ^3.0.0 |
| source-map | 0.7.6 | 0.8.0 | @stryker-mutator/core 10.1.1: ~0.7.4 |
| string-width | 7.2.0 | 8.3.0 | cliui 9.0.1: ^7.2.0 |
| string-width | 7.2.0 | 8.3.0 | wrap-ansi 9.0.2: ^7.0.0 |
| string-width | 4.2.3 | 8.3.0 | cliui 8.0.1: ^4.2.0; wrap-ansi 7.0.0: ^4.1.0; yargs 17.7.3: ^4.2.3 |
| strip-ansi | 6.0.1 | 7.2.0 | cliui 8.0.1: ^6.0.1; enquirer 2.4.1: ^6.0.1; string-width 4.2.3: ^6.0.1; wrap-ansi 7.0.0: ^6.0.0 |
| tslib | 2.8.1 | 2.9.1 | @formatjs/ecma402-abstract 2.3.6: ^2.8.0; @formatjs/fast-memoize 2.2.7: ^2.8.0; @formatjs/icu-messageformat-parser 2.11.4: ^2.8.0; @formatjs/icu-skeleton-parser 1.8.16: ^2.8.0; @formatjs/intl-localematcher 0.6.2: ^2.8.0; @stryker-mutator/api 10.1.1: ~2.8.0; @stryker-mutator/core 10.1.1: 2.8.1; @stryker-mutator/instrumenter 10.1.1: 2.8.1; @stryker-mutator/vitest-runner 10.1.1: ~2.8.0; intl-messageformat 10.7.18: ^2.8.0; rxjs 7.8.2: ^2.1.0 |
| type-fest | 4.41.0 | 5.10.0 | dot-prop 9.0.0: ^4.18.2 |
| typed-rest-client | 2.3.1 | 3.1.2 | @stryker-mutator/core 10.1.1: ~2.3.0 |
| undici-types | 8.9.0 | 8.12.3 | @types/node 26.6.6: ~8.9.0 |
| unicorn-magic | 0.3.0 | 0.4.1 | npm-run-path 6.0.0: ^0.3.0 |
| webdriver-bidi-protocol | 1.0.1 | 1.0.2 | puppeteer-core 25.16.0: 1.0.1 |
| which | 2.0.2 | 7.0.0 | cross-spawn 7.0.6: ^2.0.1 |
| why-is-node-running | 3.2.1 | 3.2.3 | vitest 5.1.0: 3.2.1 |
| wrap-ansi | 9.0.2 | 10.0.2 | cliui 9.0.1: ^9.0.0 |
| wrap-ansi | 7.0.0 | 10.0.2 | cliui 8.0.1: ^7.0.0 |
| yargs | 17.7.3 | 18.2.0 | lighthouse 13.5.0: ^17.3.1 |
| yargs-parser | 21.1.1 | 22.0.0 | lighthouse 13.5.0: ^21.0.0; yargs 17.7.3: ^21.1.1 |
