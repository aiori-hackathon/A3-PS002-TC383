# A3-PS002-TC383 · Purpose-Based Consent Recording & Withdrawal

**Team Comittea** · Institute of Engineering & Management · AIORI Hackathon 3

## Team Introduction Video
Youtube Link: https://youtu.be/wpCqELmK7v0?si=O13SYAr7yQGQs0Et

## Problem Statement
PS-002: Purpose-Based Consent Recording & Withdrawal Prototype
## Proposed solution
- A policy enforcement point that checks every data request against the user's current consent, the requester's registered purposes and the current notice version, with no caching. Anything not explicitly allowed is denied.
- A per-purpose notice hash, so a notice change requires fresh consent only for that purpose.
- An append-only, hash-chained audit log with export and verification, so tampering can be detected.
- A lifecycle test suite (12+ tests) and a demo of grant → data sharing → withdrawal → denied request → notice change.


## Live Prototype & Demo

- **Deployed Application:** https://a3-ps002-tc383.onrender.com/
- **YouTube Demo Video:** https://www.youtube.com/watch?v=muiP8mVSKcc

## Implementation Highlights

- Complete consent lifecycle: Grant → Data Sharing → Withdrawal → Request Denial → Notice Update.
- Purpose-specific consent validation and notice version checking.
- Tamper-evident, hash-chained audit ledger with verification and export.
- 28 automated lifecycle tests.

## Technical Documentation

For implementation details, architecture, API documentation, setup instructions, and testing, refer to [`src/consent-prototype/README.md`](src/consent-prototype/README.md).

**Note:** The deployed prototype uses synthetic data. Its database and audit ledger reset whenever the Render service restarts or redeploys.
