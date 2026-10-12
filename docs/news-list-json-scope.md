# JSON-only news-list negotiation

Base: f32aafacecffc39dde89a37f3b76162276142d90 (verified current main). This small port copies only the list JSONRenderer constraint and HTML-negotiation negative coverage from the reviewed deployment compatibility fix e4739ce. No deployed-line history, subscription/BYOK changes, migrations or production configuration are imported.

Nginx gzip_types application/json does not remove its default text/html type. The default DRF BrowsableAPI renderer could therefore expose and compress list HTML containing session/CSRF template information. Limit only NewsListView.renderer_classes to JSONRenderer. This corrects a scope defect; no exploitable attack was established. Global/detail renderers and authentication remain unchanged, and the existing exact-list JSON gzip boundary is unchanged.

Verification: 35 list/Nginx tests passed, including anonymous and synthetic-session Accept:text/html (406 JSON) and format=api (404 JSON). Four actual isolated Nginx probes show application/json errors, no Content-Encoding, HTML, CSRF form or username. Existing normal-list compression/decompression, detail/SSE/private probes and slow-network checks passed. Model preload/load/inference guards recorded zero calls; no user DB/Key or provider was used. Evidence: verification/news-list-json-scope.json.

The synthetic repeated-text payload compressed to1,149 bytes from37,599 summary bytes; this ratio does not predict production compression. No full backend/frontend suite, production/container/deployment tests or server access were run for this backend-only follow-up. No CI was manually rerun and previous failing/successful CI remains separate evidence. The independent Draft PR targets main and awaits review; no merge or deployment is authorized.
