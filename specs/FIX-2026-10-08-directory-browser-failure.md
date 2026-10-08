# Directory browser failure handling

## Problem

`directory.list` reports filesystem listing errors as an empty directory and logs
the private path with a traceback. The settings and setup pickers then allow the
operator to select a path that was never verified.

## Acceptance criteria

1. A genuine empty directory still returns a successful empty listing. A failed
   listing returns an explicit, fixed error without private path data in the
   response or logs.
2. Settings and setup pickers distinguish HTTP, API and malformed-response
   failures from empty directories, announce a useful error, and offer retry.
3. During loading or after failure, neither picker commits a directory; the
   previously saved form value is preserved. A later successful retry allows
   selection.
4. Phone-width and keyboard browser tests exercise failure, retry and selection.

## Verification

Use red, green, refactor for backend and browser behaviour. Mutation checks
remove the error checks and confirm focused tests fail. Run the relevant local
gate and two independent code reviews before pushing.
