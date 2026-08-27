import SwiftUI

struct SimulatorWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            header
            if let state = model.simulatorState, state.track != nil {
                SimulatorTimelineView(state: state, seek: { model.simulatorSeek(milliseconds: Int($0 * 1000)) })
                navigation(state)
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 14) { musical(state); composer(state); fixturePreview }
                    VStack(alignment: .leading, spacing: 14) { musical(state); composer(state); fixturePreview }
                }
            } else {
                PanelSurface(title: "Simulator", compact: false) { Text("Kies een current analyse. De simulator heeft geen fysieke output en wijzigt geen live deck.").foregroundStyle(BeatBeamPalette.secondaryText) }
            }
        }
        .onAppear { if model.simulatorTracks.isEmpty { model.loadSimulator() } }
        .accessibilityLabel("BeatBeam Simulator, no physical output")
    }
    private var header: some View {
        PanelSurface(title: "Simulator", compact: false) {
            VStack(alignment: .leading, spacing: 10) {
                HStack { badge("SIMULATION", color: BeatBeamPalette.brandCyan); badge("NO PHYSICAL OUTPUT", color: BeatBeamPalette.brandAmber); Spacer(); Button("Laad analyses") { model.loadSimulator() } }
                Picker("Track", selection: Binding(get: { model.simulatorState?.track?.path ?? "" }, set: { model.simulatorSelect($0) })) {
                    Text("Kies een current analyse").tag("")
                    ForEach(model.simulatorTracks) { track in Text(track.title).tag(track.path) }
                }
                if let state = model.simulatorState, let track = state.track {
                    HStack(spacing: 10) { metric("TIME", time(state.transport.positionMilliseconds) + " / " + time(state.transport.durationMilliseconds)); metric("BPM", state.transport.bpm.map { String(format: "%.1f", $0) } ?? "—"); metric("BEAT", state.transport.beat.map(String.init) ?? "—"); metric("BAR", state.transport.bar.map(String.init) ?? "—"); Button(state.transport.playing ? "Pause" : "Play") { state.transport.playing ? model.simulatorPause() : model.simulatorPlay() }; Button("Restart") { model.simulatorRestart() } }
                    Text(track.path).font(.system(size: 10, design: .monospaced)).foregroundStyle(BeatBeamPalette.secondaryText).lineLimit(1)
                }
            }
        }
    }
    private func navigation(_ state: SimulatorState) -> some View {
        PanelSurface(title: "Jump", compact: true) {
            VStack(alignment: .leading, spacing: 8) {
                HStack { Button("← Section") { model.simulatorNavigate("/api/simulator/previous-section") }; Button("Section →") { model.simulatorNavigate("/api/simulator/next-section") }; Button("← Event") { model.simulatorNavigate("/api/simulator/previous-event") }; Button("Event →") { model.simulatorNavigate("/api/simulator/next-event") } }
                HStack { ForEach(["MIX_IN", "MAIN", "BREAK", "MIX_OUT"], id: \.self) { role in Button(role.replacingOccurrences(of: "_", with: " ")) { model.simulatorJumpCue(role) }.disabled(!state.smartCues.contains { $0.role == role && $0.planned == true }) } }
            }
        }
    }
    private func musical(_ state: SimulatorState) -> some View { PanelSurface(title: "Musical State", compact: true) { VStack(alignment: .leading, spacing: 6) { Text("ANALYZED ONLY").foregroundStyle(BeatBeamPalette.brandCyan); Text("Energy \(state.continuousMusicalState?.relativeEnergy.map { String(format: "%.2f", $0) } ?? "—")"); Text("RME \(state.rme?.type ?? "none")"); Text("Envelope \(state.eventEnvelope?.phase ?? "inactive")") } } }
    private func composer(_ state: SimulatorState) -> some View {
        let moving = state.composition?.selectedPrimitives?["moving"]
        let par = state.composition?.selectedPrimitives?["par"]
        let signature = state.composition?.compositionSignature
        let variation = state.composition?.variation
        return PanelSurface(title: "Dynamic Composer", compact: true) {
            VStack(alignment: .leading, spacing: 6) {
                Text(state.composition?.selectedPrimitives != nil ? "Preview composition active" : "No composition")
                Text("Move \(primitive(moving, "movement_pattern")) · Dimmer \(primitive(moving, "dimmer_motif"))")
                Text("Palette \(primitive(par, "palette")) · Color \(primitive(par, "color_animation"))")
                Text("Participation \(primitive(moving, "fixture_partition")) · Pulse \(primitive(par, "pulse"))")
                Text("Relation \(primitiveValue(signature, "palette_relationship")) · \(primitiveValue(variation, "repeat_classification"))")
                    .foregroundStyle(BeatBeamPalette.secondaryText)
                Text("Fixture intents + primitives are from this timeline position").foregroundStyle(BeatBeamPalette.secondaryText)
                Text("Physical output: NONE").foregroundStyle(BeatBeamPalette.brandAmber)
            }
            .font(.system(size: 10, weight: .medium, design: .monospaced))
        }
    }
    private func primitive(_ values: [String: PreviewPrimitiveValue]?, _ key: String) -> String { primitiveValue(values, key) }
    private func primitiveValue(_ values: [String: PreviewPrimitiveValue]?, _ key: String) -> String { values?[key]?.displayText ?? "—" }
    private var fixturePreview: some View { PanelSurface(title: "Simulated Preview Map", compact: true) { ScrollView(.horizontal, showsIndicators: false) { HStack(spacing: 8) { ForEach(model.slotEditors) { editor in let preview = model.simulatorSlotPreviews[editor.id]; VStack(alignment: .leading, spacing: 5) { RoundedRectangle(cornerRadius: 5).fill(simulatorColor(preview)).frame(width: 72, height: 34); Text(editor.label).font(.caption2); Text(preview?.motionActive == true ? "moving" : "steady").font(.caption2).foregroundStyle(BeatBeamPalette.secondaryText) } } } } } }
    private func simulatorColor(_ preview: SlotPreview?) -> Color { guard let preview else { return .black.opacity(0.4) }; return Color(red: Double(preview.red) / 255, green: Double(preview.green) / 255, blue: Double(preview.blue) / 255).opacity(max(0.15, Double(preview.brightness) / 255)) }
    private func time(_ milliseconds: Int) -> String { String(format: "%d:%02d", milliseconds / 60000, (milliseconds / 1000) % 60) }
    private func badge(_ text: String, color: Color) -> some View { Text(text).font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(color).padding(.horizontal, 7).padding(.vertical, 4).background(color.opacity(0.15)).clipShape(Capsule()) }
    private func metric(_ title: String, _ value: String) -> some View { VStack(alignment: .leading, spacing: 2) { Text(title).font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundStyle(BeatBeamPalette.secondaryText); Text(value).font(.system(size: 13, weight: .semibold, design: .monospaced)) } }
}

private struct SimulatorTimelineView: View {
    let state: SimulatorState
    let seek: (Double) -> Void
    var body: some View {
        PanelSurface(title: "Musical Timeline", compact: false) {
            GeometryReader { proxy in
                let duration = max(0.001, state.timeline.durationSeconds)
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 8).fill(BeatBeamPalette.mutedBackground)
                    ForEach(state.timeline.sections, id: \.stableID) { section in
                        RoundedRectangle(cornerRadius: 4).fill(Color.cyan.opacity(0.12 + (section.relativeEnergy ?? 0.3) * 0.35)).frame(width: width(section.endSeconds-section.startSeconds, proxy.size.width, duration), height: 40).offset(x: width(section.startSeconds, proxy.size.width, duration), y: 34)
                    }
                    ForEach(state.timeline.events) { event in
                        Rectangle().fill(event.type == "DROP" ? Color.orange : Color.pink).frame(width: 2, height: 82).offset(x: width(event.startSeconds, proxy.size.width, duration), y: 10)
                    }
                    ForEach(state.timeline.smartCues.filter(\.planned)) { cue in
                        Circle().fill(Color.green).frame(width: 7, height: 7).offset(x: width(cue.startSeconds, proxy.size.width, duration)-3, y: 5)
                    }
                    Rectangle().fill(Color.white).frame(width: 2).offset(x: width(state.timeline.playheadSeconds, proxy.size.width, duration))
                }
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                    let fraction = max(0.0, min(1.0, Double(value.location.x / max(1, proxy.size.width))))
                    seek(fraction * duration)
                })
            }
            .frame(height: 92)
            Text("Sections · RME/events · Smart Cues · playhead").font(.caption).foregroundStyle(BeatBeamPalette.secondaryText)
        }
    }
    private func width(_ seconds: Double, _ width: CGFloat, _ duration: Double) -> CGFloat { CGFloat(max(0, min(1, seconds / duration))) * width }
}
