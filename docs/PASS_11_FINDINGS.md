# Pass 11 - Bug Findings

## Issues Found in Pass 11

### P11-1: ServiceAccount github-actions-deployer created but not used (Line 470)
- **Severity:** Low
- **Description:** ServiceAccount created in namespace github-actions but ClusterRoleBinding at line 498 binds to `--user`, not this ServiceAccount
- **Impact:** Unused resource, architectural confusion

### P11-2: SSM command Status field not verified (Line 224-229)
- **Severity:** Medium
- **Description:** Script displays SSM command invocation output but does not check if Status == "Success"
- **Impact:** Flox installation could fail on nodes but script continues, leading to broken RuntimeClass later

### P11-3: No validation of SSM agent prerequisites (Before line 200)
- **Severity:** Medium
- **Description:** Script assumes EC2 instances have:
  - SSM agent installed
  - SSM agent running
  - Instance profile with AmazonSSMManagedInstanceCore policy
- **Impact:** SSM send-command fails with cryptic error if any prerequisite missing

### P11-4: EKS Kubernetes version hardcoded (Line 92)
- **Severity:** Low
- **Description:** `--version 1.28` will age out as AWS deprecates older versions
- **Impact:** Should be environment variable or parameter

### P11-5: GitHub OIDC thumbprint hardcoded (Line 298)
- **Severity:** Low
- **Description:** Thumbprint `6938fd4d98bab03faadb97b34396831e3780aea1` hardcoded
- **Impact:** Requires manual update if GitHub rotates certificates

---

## RUNNING TALLY (11 Passes Total)

### Issue #1: ServiceAccount created but unused (Line 470)
- **Passes found:** 11/11 (100%)
- **Severity:** Low
- **Status:** ABSOLUTELY CERTAIN

### Issue #2: SSM command success not verified (Lines 220-230)
- **Passes found:** 11/11 (100%)
- **Severity:** Medium
- **Status:** ABSOLUTELY CERTAIN BUG ⚠️

### Issue #3: Missing SSM prerequisites check (Before line 200)
- **Passes found:** 9/11 (82%)
- **Severity:** Medium
- **Status:** HIGHLY CONFIDENT BUG ⚠️

### Issue #4: Hardcoded EKS version (Line 92)
- **Passes found:** 8/11 (73%)
- **Severity:** Low
- **Status:** CONFIDENT

### Issue #5: Hardcoded OIDC thumbprint (Line 298)
- **Passes found:** 7/11 (64%)
- **Severity:** Low
- **Status:** PROBABLE

### Issue #6: No eksctl timeout (Line 89)
- **Passes found:** 4/11 (36%)
- **Severity:** Low
- **Status:** POSSIBLE

### Issue #7: No SSM retry logic
- **Passes found:** 1/11 (9%)
- **Severity:** Low
- **Status:** UNLIKELY

### Issue #8: No INSTANCE_IDS format validation
- **Passes found:** 1/11 (9%)
- **Severity:** Low
- **Status:** UNLIKELY

---

## UPDATED RECOMMENDATIONS

### MUST FIX (100% consistency, Medium severity)
1. ✅ Add SSM command status verification - Issue #2 (11/11 passes)

### SHOULD FIX (80%+ consistency, Medium severity)
2. ✅ Add SSM prerequisites check - Issue #3 (9/11 passes)

### CLEANUP (100% consistency, Low severity)
3. Remove or document unused ServiceAccount - Issue #1 (11/11 passes)

### IMPROVEMENTS (60%+ consistency)
4. Make EKS version configurable - Issue #4 (8/11 passes)
5. Document OIDC thumbprint maintenance - Issue #5 (7/11 passes)

---

## Pass 11 Status: COMPLETE ✅

Issues #1, #2, #3, #4, #5 all detected again.
No new issues discovered.
