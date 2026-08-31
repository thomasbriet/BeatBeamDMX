# BeatBeam Remote UIKit V1 parity matrix

UIKit V1 is the default internal presentation route. The user accepted all
four fixed landscape surfaces in Simulator review on 2026-08-31. The legacy
SwiftUI route remains available through `BBRemotePresentationMode` pending a
separate cleanup decision and the required physical-iPad landscape review.
Both routes use the same `RemoteStore`; UIKit does not own networking, remote
state, acknowledgements, revisions, or lease state.

| Surface | Existing contract | UIKit V1 control/readout | Authority/action route |
| --- | --- | --- | --- |
| Shell | Live / Override / Status / Settings | Fixed top hardware navigation | Presentation-only tab state |
| Shell | connection + QR | Compact LED/label + QR pad | `RemoteStore.connectionState`, `showScanner` |
| Live | track / artist | Now Playing | `RemoteLiveStateV2.track` |
| Live | deck / BPM / beat / bar / time | Compact readouts | `RemoteLiveStateV2.track` |
| Live | production mode | Show Now mode | `show.configuredProductionMode` |
| Live | actual frame / fallback | Explicit frame source + fallback | `show.physicalFrameSource`, `fallbackActive` |
| Live | musical state | Section/event readout | `musicalState` |
| Live | override summary | One concise summary | `overrides` |
| Live | rendered output | Compact exact fixture tiles | post-authority `output.fixtures` |
| Live | DMX | Physical vs Preview / No Physical DMX | `dmx`, never a control gate |
| Override | Auto + 10 exact colors + Rainbow | Large fixed 2×6 bank | `set_color` |
| Override | Smoke safe pending state | Tall disabled pad right of Purple/Rainbow | No command; setup pending |
| Override | 16 exact combinations | Fixed 2×8 split-color bank | `set_color_combo` |
| Override | phrase Auto + capability vocabulary | Compact 2-column bank | `set_phrase` |
| Override | Energy Auto/Low/Mid/High | Custom direct-touch vertical `UIControl` | `set_energy`, discrete level changes only |
| Override | five hold effects | Hardware hold pads | `beginMomentary` / `endMomentary`; existing exact leases |
| Override | six one-shots | Compact secondary pads | `trigger_cue` |
| Override | Release All | Compact safety strip | `release_all` |
| Override | Blackout | State-driven danger pad/banner | `blackout_on` / `blackout_off` |
| Status | connection/host/protocol/scope | Left connection zone | authoritative store/state |
| Status | reconnect + QR/re-pair | Compact normal-size pads | existing reconnect/scanner routes |
| Status | Backend/Renderer/VDJ/SongAnalyzer/DMX/Transport/Output | Dense LED health grid | authoritative state only |
| Status | frame/fixtures/failures/freshness | Runtime readouts | authoritative state/revisions |
| Settings | host/keep awake/auto reconnect | Connection preferences | existing lifecycle semantics |
| Settings | app/protocol/scope | App / Remote bank | bundle + authoritative state |
| Settings | forget pairing | Confirmed compact danger action | `forgetConnection` |
| Settings | Revert Baseline | Confirmed production action | `revert_baseline` |
| Settings | Enable Dynamic Composer | Confirmed production action | `enable_dynamic_composer` |

No UIKit surface uses a local beat timer, local combo swap, independent show
state, direct endpoint construction, a separate event stream, or DMX
connectivity as a control availability gate.
