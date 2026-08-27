import SwiftUI

struct SimulatorWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PanelSurface(title: "Simulator", compact: false) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack { badge("SIMULATION", color: BeatBeamPalette.brandCyan); badge("NO PHYSICAL OUTPUT", color: BeatBeamPalette.brandAmber); Spacer(); Button("Laad analyses") { model.loadSimulator() } }
                    Picker("Track", selection: Binding(get: { model.simulatorState?.track?.path ?? "" }, set: { model.simulatorSelect($0) })) {
                        Text("Kies een current analyse").tag("")
                        ForEach(model.simulatorTracks) { track in Text(track.title).tag(track.path) }
                    }
                    if let state = model.simulatorState, let track = state.track {
                        Text(track.path).font(.system(size: 11, design: .monospaced)).foregroundStyle(BeatBeamPalette.secondaryText).lineLimit(1)
                        HStack(spacing: 8) {
                            metric("TIME", time(state.transport.positionMilliseconds) + " / " + time(state.transport.durationMilliseconds))
                            metric("BPM", state.transport.bpm.map { String(format: "%.1f", $0) } ?? "—")
                            metric("BEAT", state.transport.beat.map(String.init) ?? "—")
                            metric("BAR", state.transport.bar.map(String.init) ?? "—")
                            Button(state.transport.playing ? "Pause" : "Play") { state.transport.playing ? model.simulatorPause() : model.simulatorPlay() }
                            Button("Restart") { model.simulatorRestart() }
                        }
                        Slider(value: Binding(get: { Double(state.transport.positionMilliseconds) }, set: { model.simulatorSeek(milliseconds: Int($0)) }), in: 0...Double(max(1, state.transport.durationMilliseconds)))
                    }
                }
            }
            if let state = model.simulatorState, state.track != nil {
                HStack(alignment: .top, spacing: 14) {
                    PanelSurface(title: "Musical state", compact: true) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("ANALYZED ONLY").foregroundStyle(BeatBeamPalette.brandCyan)
                            Text("Energy \(state.continuousMusicalState?.relativeEnergy.map { String(format: "%.2f", $0) } ?? "—")")
                            Text("RME \(state.rme?.type ?? "none")")
                            Text("Envelope \(state.eventEnvelope?.phase ?? "inactive")")
                        }
                    }
                    PanelSurface(title: "Composer", compact: true) { VStack(alignment: .leading, spacing: 6) { Text(state.composition?.dynamicComposerActive == true ? "Dynamic Composer" : "No composition"); Text("Preview-only fixture intent"); Text("Physical output: NONE").foregroundStyle(BeatBeamPalette.brandAmber) } }
                    PanelSurface(title: "Smart Cues", compact: true) { ForEach(state.smartCues) { cue in Text("\(cue.role ?? "CUE")  \(cue.positionMilliseconds.map(time) ?? "MISSING")") } }
                }
            }
        }
        .onAppear { if model.simulatorTracks.isEmpty { model.loadSimulator() } }
        .accessibilityLabel("BeatBeam Simulator, no physical output")
    }
    private func time(_ milliseconds: Int) -> String { String(format: "%d:%02d", milliseconds / 60000, (milliseconds / 1000) % 60) }
    private func badge(_ text: String, color: Color) -> some View { Text(text).font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(color).padding(.horizontal, 7).padding(.vertical, 4).background(color.opacity(0.15)).clipShape(Capsule()) }
    private func metric(_ title: String, _ value: String) -> some View { VStack(alignment: .leading, spacing: 2) { Text(title).font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.secondaryText); Text(value).font(.system(size: 13, weight: .semibold, design: .monospaced)) } }
}
