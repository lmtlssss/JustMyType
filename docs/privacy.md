# privacy

Cloud checks are off at installation. Enabling them sends the current bounded
goal, proposed action, relevant tool-result snippets and configured constraints
to `https://api.typesafe.ai/v1/systemone`. TypeSafe handles those requests under
its own terms. This project does not make a provider retention guarantee.

No full transcript is read or uploaded. No analytics endpoint is used. No API
key is stored by the plugin. Supply `TYPESAFE_API_KEY` through the environment
or a trusted credential-runner argv configured in the private user directory.

Redaction removes common credential fields, bearer tokens, key-shaped values,
private-key blocks and known credential values in the process environment.
This is best-effort. It does not guarantee that arbitrary private content is
removed. Do not enable cloud mode on material that must not leave the machine.

Local SQLite keeps at most 128 recent turns, six bounded observations per turn,
and 512 metadata-only assessment records. Turns older than seven days are
removed on the next prompt. State is keyed by session and turn, not directory.
Uninstall retains private data. Delete the reported data directory manually
only after deciding that those records and settings are no longer needed.

The public tests and demo use authored synthetic inputs. Private account data,
user transcripts and desktop captures are not demo sources.

Version 0.2.0 can send several isolated requests for one action. These requests
reuse the same redacted user instructions and evidence with derived literal-field
candidates. There is no new transcript access or credential source. More requests
can mean more token usage. The result retains model signals and exact comparisons;
those results can include the relevant source field and numeric bound.
