# RevokeLab Quality Report

## Test information

* Tester: Bushra
* Date: 2026-10-09
* Git commit tested: To be recorded
* Python version: To be recorded
* Total automated tests: 10
* Automated tests passed: 10
* Automated tests failed: 0

## Manual access checks

| Check | Expected | Actual | Pass/Fail | Screenshot |
|---|---|---|---|---|
| Alice accesses Project Red before removal | 200 | 200 | PASS | 01-alice-access-before-removal.png |
| Bob attempts to access Project Red | 403 | 403 | PASS | 02-bob-access-denied.png |
| Admin removes Alice | 200 and revoked | 200, revoked | PASS | 03-alice-revoked.png |
| Removed Alice accesses Project Red | 403 | 403 | PASS | 04-alice-access-denied-after-removal.png |
| Removed Alice creates a message | 403 | 403 | PASS | 05-alice-message-denied-after-removal.png |
| Admin restores Alice | 200 and active | 200, active | PASS | 06-alice-restored.png |
| Restored Alice accesses Project Red | 200 | 200 | PASS | 09-alice-restored.png |         |

## Samia's experiment results

| Run | Mode | Cutoff | Expected | Actual | Pass/Fail | Evidence |
|---|---|---:|---|---|---|---|
| 1 | connection-only | 1 | fail | fail | PASS | 07-connection-only-result.png |
| 2 | continuous | 1 | pass | pass | PASS | 08-continuous-result-part1.png, 08-continuous-result-part2.png, 08-continuous-result-part3.png |
| 3 | connection-only | 5 | fail | fail | PASS | 07-connection-only-result.png |
| 4 | continuous | 5 | pass | pass | PASS | 08-continuous-result-part1.png, 08-continuous-result-part2.png, 08-continuous-result-part3.png |
| 5 | connection-only | 10 | fail | fail | PASS | 07-connection-only-result.png |
| 6 | continuous | 10 | pass | pass | PASS | 08-continuous-result-part1.png, 08-continuous-result-part2.png, 08-continuous-result-part3.png |
## Evidence-quality checks

* All runs contain timestamps: Yes
* All runs contain ordered events: Yes
* All runs contain an access-removal event: Yes
* All runs contain a message-creation event: Yes
* All runs contain a final observation: Yes
* Results can be reproduced: Not yet confirmed
* Passwords or secrets visible in evidence: No
## Problems found

* The initial message-creation test returned 201 because Alice's access had not yet been revoked.
* After revoking Alice, the exact required message test returned 403 as expected.
* No access-control failure was observed in the final manual checks.

## Final conclusion

The manual access-control checks passed. Alice could access Project Red before removal, Bob was denied access, and Alice was denied project access and message creation after revocation. After the administrator restored Alice's membership, project access returned successfully.

Samia's six experiment results matched the expected outcomes: connection-only runs were classified as fail, while continuous authorization runs were classified as pass.

The Git commit, Python version, reproducibility, and evidence-secret checks must be confirmed before final submission.
