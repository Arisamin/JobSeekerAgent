# Flowchart: Telegram Apply State Machine (Dual Apply Paths)

```mermaid
flowchart TD
	A[User in BROWSING_NEW or BROWSING_DB] --> B{Command = Apply?}
	B -- no --> Z[Stay in browse flow]
	B -- yes --> C[Initialize APPLYING state and fixed fields]

	C --> D{Run mode}
	D -- testing --> E[Pre-scan required fields]
	D -- normal --> F[Incremental Q&A starts]

	E --> G[Build dynamic form fields]
	F --> H[Ask next unanswered field]
	G --> H

	H --> I{More unanswered fields?}
	I -- yes --> H
	I -- no --> J[Rescan with seeded answers]

	J --> K{Apply entry click result}
	K -- Easy Apply modal visible --> L[Wizard scan scope = modal]
	K -- External page same tab --> M[Scan scope = current page]
	K -- External page popup/new tab --> N[Scan scope = new page]
	K -- unresolved --> O[No additional fields]

	L --> P[Generic field extraction]
	M --> P
	N --> P

	P --> Q{New fields found?}
	Q -- yes --> R[Merge + dedupe labels/keys; continue APPLYING]
	Q -- no --> S[Show APPLY_CONFIRM summary]
	O --> S
	R --> H

	S --> T{User reply}
	T -- Preview --> U[Run fill flow in preview mode]
	T -- Submit --> V[Run fill + submit]
	T -- Cancel --> W[Abort apply and restore previous state]

	U --> X{Flow type}
	V --> X
	X -- Easy Apply wizard --> Y[Wizard stepping: Next/Review/Submit]
	X -- External Apply page --> AA[Direct page-form fill path]

	Y --> AB[Return result + update DB status]
	AA --> AB
	W --> AB
```

## Notes

- Easy Apply remains wizard-driven and uses modal step progression semantics.
- External Apply flow can be same-tab or popup/new-tab and is scanned as a page form, not a modal wizard.
- Dynamic rescans are answer-seeded so later pages become discoverable.
