# Pseudocode: the enforcement decision (matches the enforcement flowchart)

```
decide(api_key, user_pid, purpose):
  validate body shape                          else DENY ERROR        # malformed input fails closed
  begin transaction (BEGIN IMMEDIATE: lock ledger head)
    requester = authenticate(api_key)          else DENY REQ_AUTH
    purpose in requester.allowed_purposes      else DENY REQ_PURPOSE
    notice = current_notice(purpose)           else DENY NO_NOTICE
    ev = latest_consent_event(user_pid, purpose)     # GRANT/WITHDRAW only; ALLOW, DENY,
                                                     # GRANT_REJECTED never change consent state
    ev is None                    -> DENY NO_CONSENT        # never consented OR unknown user (same answer)
    ev.type == WITHDRAW           -> DENY CONSENT_WITHDRAWN
    ev.notice_hash != notice.hash -> DENY NOTICE_STALE
    data = mock_api.get_records(user_pid, purpose, internal_token)   # only this purpose's fields
    append ALLOW; COMMIT; return 200, data
  every DENY: append DENY(reason) in the same transaction; COMMIT; return 403, reason
  any exception / timeout: ROLLBACK; discard data; return 403 ERROR;
      then best-effort DENY(ERROR) in a fresh transaction, else write logs/errors.log
```

## Consent rules
```
grant(user, purpose, notice_hash_seen):
  notice = current_notice(purpose)
  no notice                      -> append GRANT_REJECTED(NO_NOTICE),            409
  hash missing                   -> append GRANT_REJECTED(HASH_MISSING),         409
  hash != notice.hash            -> append GRANT_REJECTED(NOTICE_HASH_MISMATCH), 409
  else                           -> append GRANT(notice.hash)

withdraw(user, purpose):         # always accepted, idempotent, no hash check
  append WITHDRAW

publish_notice(purpose, text):   # administrator
  version = last + 1; hash = SHA256(canonical_json({purpose, version, text}))
  insert notice (immutable) ; append NOTICE_PUBLISHED   # old consents become NOTICE_STALE automatically
```

## Ledger
```
append(event):                   # the only write path (Storage Gateway)
  seq = head.seq + 1 ; prev = head.entry_hash
  entry_hash = SHA256(prev || canonical_json({seq, ts, event, user_pid, purpose, notice_hash, actor, reason, detail}))
  INSERT   (triggers abort any UPDATE or DELETE)

verify(expected_head?):          # server endpoint and scripts/verify_audit.py
  for each entry in seq order: check seq contiguous, prev_hash links, entry_hash recomputes
  if expected_head given: it must appear in the chain, else truncation/rewrite is reported
```
