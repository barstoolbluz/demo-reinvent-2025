# Pass 12 - Bug Findings

## Issues Found in Pass 12

### P12-1: ServiceAccount resource created but unused in IAM workflow (Line 470)
- **Severity:** Low
- **Description:** Creates `github-actions-deployer` ServiceAccount but the ClusterRoleBinding binds to User (line 498), and IAM mapping uses username (line 517)
- **Impact:** Dead code, confusing architecture

### P12-2: No automated verification of SSM command success (Line 224-229)
- **Severity:** Medium
- **Description:** Script shows SSM invocation output but doesn't programmatically verify Status field is "Success"
- **Impact:** Flox installation failure on nodes goes undetected, RuntimeClass will be created but won't work

### P12-3: Missing SSM agent and permissions validation (Before line 200)
- **Severity:** Medium
- **Description:** No check that EC2 instances have:
  - SSM agent installed and running
  - IAM instance profile with SSM permissions (AmazonSSMManagedInstanceCore)
- **Impact:** SSM send-command fails with unclear error message

### P12-4: EKS Kubernetes version not configurable (Line 92)
- **Severity:** Low
- **Description:** Hardcoded to `--version 1.28`
- **Impact:** Will require script updates as AWS deprecates versions

### P12-5: GitHub OIDC certificate thumbprint hardcoded (Line 298)
- **Severity:** Low
- **Description:** Thumbprint `6938fd4d98bab03faadb97b34396831e3780aea1` requires manual maintenance
- **Impact:** Will break if GitHub rotates their OIDC certificates

### P12-6: No timeout on eksctl cluster creation (Line 89)
- **Severity:** Low
- **Description:** eksctl create cluster has no --timeout parameter
- **Impact:** Could hang indefinitely if AWS API issues occur

---

## FINAL TALLY (12 Passes Total)

### Issue #1: ServiceAccount created but unused (Line 470)
- **Passes found:** 12/12 (100%)
- **Severity:** Low
- **Status:** ABSOLUTELY CERTAIN ✅

### Issue #2: SSM command success not verified (Lines 220-230)
- **Passes found:** 12/12 (100%)
- **Severity:** Medium
- **Status:** ABSOLUTELY CERTAIN BUG ⚠️

### Issue #3: Missing SSM prerequisites check (Before line 200)
- **Passes found:** 10/12 (83%)
- **Severity:** Medium
- **Status:** HIGHLY CONFIDENT BUG ⚠️

### Issue #4: Hardcoded EKS version (Line 92)
- **Passes found:** 9/12 (75%)
- **Severity:** Low
- **Status:** CONFIDENT ✅

### Issue #5: Hardcoded OIDC thumbprint (Line 298)
- **Passes found:** 8/12 (67%)
- **Severity:** Low
- **Status:** PROBABLE ✅

### Issue #6: No eksctl timeout (Line 89)
- **Passes found:** 5/12 (42%)
- **Severity:** Low
- **Status:** POSSIBLE

### Issue #7: No SSM retry logic
- **Passes found:** 1/12 (8%)
- **Severity:** Low
- **Status:** UNLIKELY

### Issue #8: No INSTANCE_IDS format validation
- **Passes found:** 1/12 (8%)
- **Severity:** Low
- **Status:** UNLIKELY

---

## FINAL SUMMARY TABLE

| Priority | Issue | Location | Passes | Severity | Action |
|----------|-------|----------|--------|----------|--------|
| **P0** | SSM success not verified | Lines 220-230 | 12/12 (100%) | Medium | **FIX** |
| **P1** | SSM prerequisites not checked | Before line 200 | 10/12 (83%) | Medium | **FIX** |
| **P2** | ServiceAccount unused | Line 470 | 12/12 (100%) | Low | **CLEANUP** |
| **P3** | EKS version hardcoded | Line 92 | 9/12 (75%) | Low | **IMPROVE** |
| **P4** | OIDC thumbprint hardcoded | Line 298 | 8/12 (67%) | Low | **IMPROVE** |
| **P5** | No eksctl timeout | Line 89 | 5/12 (42%) | Low | **OPTIONAL** |

---

## Pass 12 Status: COMPLETE ✅

All 5 top issues detected again, plus Issue #6 appeared.
No new issues discovered.
Consistency remains very high for top issues.

---

## READY FOR FIX PLAN

Top issues validated across 12 independent passes:
- **2 bugs to fix** (Issues #2, #3)
- **1 cleanup** (Issue #1)
- **2 improvements** (Issues #4, #5)
- **1 optional** (Issue #6)
