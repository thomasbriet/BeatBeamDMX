import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LiveShowUxTests(unittest.TestCase):
    def setUp(self):
        self.native = (ROOT / "native" / "BeatBeamDMXApp.swift").read_text(encoding="utf-8")
        self.live = (ROOT / "native" / "LiveShowUX.swift").read_text(encoding="utf-8")
        self.backend = (ROOT / "beatbeam_app.py").read_text(encoding="utf-8")

    def test_live_show_has_operational_hierarchy_and_keeps_raw_diagnostics_advanced(self):
        for text in (
            'PanelSurface(title: "Live Show"',
            '"NOW PLAYING / MASTER"',
            'PanelSurface(title: "Decks"',
            'PanelSurface(title: "Musical State"',
            'PanelSurface(title: "Current Event"',
            'PanelSurface(title: "Dynamic Composer"',
            'PanelSurface(title: "Fixture Groups"',
            'PanelSurface(title: "Manual / Safety"',
        ):
            self.assertIn(text, self.live)
        self.assertIn('case advanced = "Advanced"', self.native)
        self.assertIn('DebugInspectorView()', self.live)

    def test_live_show_deck_cards_use_existing_typed_authority_and_readiness_fields(self):
        for text in (
            'let isMaster: Bool?',
            'let isActive: Bool?',
            'let prewarmStatus: String?',
            'let analysisStatus: String?',
            'let isPlaying: Bool?',
            'liveAnalysisState(deck)',
        ):
            self.assertIn(text, self.native + self.live)
        self.assertIn('"is_playing": bool(raw.get("is_playing"))', self.backend)

    def test_normal_baseline_and_no_rme_are_not_presented_as_errors(self):
        self.assertIn('value == "existing_autoshow" ? "BASELINE"', self.live)
        self.assertIn('"No current musical event. Continuous state remains active."', self.live)
        self.assertIn('productionFallbackReason', self.live)

    def test_recovered_state_poll_clears_only_its_own_status_error(self):
        poller = self.native[
            self.native.index('private func startPolling()'):
            self.native.index('private func loadPorts()')
        ]
        self.assertIn('try await refreshState()', poller)
        self.assertIn('clearRecoveredStatusPollError()', poller)
        self.assertIn('errorText.hasPrefix("Status ophalen mislukt:")', poller)

    def test_preview_remains_explicit_and_non_authoritative(self):
        self.assertIn('"Venue layout stays preview-only. Explicit Physical Aim and Move controls can lease bounded Pan/Tilt', self.live)
        self.assertIn('"Map editing is preview-only. Only explicit Physical Aim or Move actions lease bounded Pan/Tilt', self.native)
        self.assertIn('AutoShowControlView()', self.live)
        self.assertIn('struct AutoShowWorkspaceView: View', self.live)
        self.assertIn('case autoShow = "Auto Show"', self.native)
        live_show_section = self.live[self.live.index('struct LiveShowWorkspaceView'):self.live.index('// MARK: - Preview and advanced workspaces')]
        self.assertNotIn('Pulse Test (Preview only)', live_show_section)
        self.assertIn('"auto_show -> current_values"', self.native)

    def test_stage_map_keeps_autoshow_separate_and_explains_calibration_vectors(self):
        preview_section = self.live[
            self.live.index('struct PreviewComposerWorkspaceView'):
            self.live.index('struct AutoShowWorkspaceView')
        ]
        self.assertNotIn('AutoShowControlView()', preview_section)
        for text in (
            'CALIBRATION LEGEND',
            'AMBER F',
            'BLUE / CYAN',
            'RED / MAGENTA',
            'DOTTED LINE',
            'Red fixture glow is live preview/selection feedback',
            'CALIBRATION ACTIVE',
            'private let stageMapInspectorWidthDefaultsKey = "BeatBeamDMX.stageMap.inspectorWidth"',
            'struct StageMapResizableSplitView<Left: View, Right: View>: NSViewRepresentable',
            'splitView.isVertical = true',
            'splitView.delegate = context.coordinator',
            'splitViewDidResizeSubviews',
            'UserDefaults.standard.set(Double(width), forKey: stageMapInspectorWidthDefaultsKey)',
            'StageMapResizableSplitView(',
            'ScrollView(.vertical)',
            'singlePrimaryView: true',
            'primaryShows3D || show3D',
            'singlePrimaryView ? primaryShows3D : show3D',
            'struct VenueTargetTestPanel',
            'TEST ALL IN PREVIEW',
            'VenueTargetResultSetState',
            'TARGETED •',
            'FIXTURE DETAILS',
            'selectedVenueTargetZone',
            'selectedVenueTargetPosition',
            'private let zones = ["NEAR", "MID", "FAR", "REAR"]',
            'private let positions = ["LEFT", "CENTER", "RIGHT"]',
            'previewVenueTargetSlotIDs',
            'testAllMovingHeadsInPreview',
            'physicalCommandSent',
            'previewVenueTargetStartPanDegrees',
            'struct VenueTargetPreviewVisual',
            'venueTargetPreview: model.venueTargetPreviewVisual(for: editor.id)',
            'worldProjectedAbsoluteBeamPoint(',
            'interpolatedVenueTargetEndpoint(',
            'currentPanDegrees: currentPan',
            'targetPanDegrees: targetPan',
            '!previewTargetActive',
            'MOVE TO TARGET',
            'RELEASE TEST',
            'ScrollView(.horizontal, showsIndicators: false)',
            'title: "TOP VIEW"',
            'detail: "Forward → Back"',
            'title: "FRONT / BACK / SIDE"',
            'detail: "Up → Down"',
            'label: "FORWARD"',
            'label: "UP"',
        ):
            self.assertIn(text, self.native)

        calibration_arrow = self.native[
            self.native.index('private func calibrationAxisArrow'):
            self.native.index('private func calibrationAxisTarget', self.native.index('private func calibrationAxisArrow'))
        ]
        self.assertIn('case .top:', calibration_arrow)
        self.assertIn('case .front, .back, .side:', calibration_arrow)
        self.assertNotIn('basis.right', calibration_arrow)

    def test_manual_and_physical_state_remain_visible_without_new_control_engine(self):
        self.assertIn('model.blackout()', self.live)
        self.assertIn('"MANUAL OVERRIDE ACTIVE"', self.live)
        self.assertIn('"PHYSICAL DISCONNECTED"', self.live)
        self.assertIn('Preview remains usable', self.live)

    def test_live_show_restores_existing_dmx_connection_controls(self):
        for text in (
            'LiveDmxConnectionCard()',
            'PanelSurface(title: "Physical DMX"',
            'Picker("DMX interface", selection: $model.selectedPortLabel)',
            '"CONNECT DMX"',
            '"RECONNECT"',
            '"DISCONNECT"',
            'model.refreshPorts()',
            'model.connectDMX()',
            'model.reconnectDMX()',
            'model.disconnectDMX()',
            'DMX CONNECTED',
            'DMX DISCONNECTED',
        ):
            self.assertIn(text, self.live)
        for text in (
            'func connectDMX()',
            'func reconnectDMX()',
            'func disconnectDMX()',
            'selectedPortDefaultsKey',
            'UserDefaults.standard.set(selectedPortLabel, forKey: selectedPortDefaultsKey)',
            '!response.ports.contains(where: { $0.label == selectedPortLabel })',
            '"/api/dmx/connect"',
            '"/api/dmx/disconnect"',
        ):
            self.assertIn(text, self.native)

    def test_movement_lab_picker_exposes_each_existing_full_sphere_v3_identity_once(self):
        panel = self.native[
            self.native.index('struct MovementLabPanel'):
            self.native.index('struct VenueGeometryPanel')
        ]
        effects = (
            "full_sphere_explode", "floor_hold_explode", "rear_hold_split",
            "full_sphere_cannon", "floor_forward_cannon", "dome_sweep_3d",
            "floor_forward_sweep", "forward_rear_arc", "cross_3d",
            "volumetric_orbit", "volumetric_figure_8", "energy_scatter", "fan_3d",
        )
        for effect in effects:
            with self.subTest(effect=effect):
                self.assertEqual(1, panel.count(f'"{effect}"'))
        self.assertIn('effectID: movementLabEffectID', self.native)
        self.assertIn('"/api/dmx/movement-lab/play"', self.native)

    def test_live_presentation_does_not_introduce_a_second_backend_or_production_selector(self):
        self.assertNotIn('URLSession', self.live)
        self.assertNotIn('select_production_show_source', self.live)
        self.assertIn('ENABLE DYNAMIC COMPOSER', self.live)
        self.assertIn('REVERT TO BASELINE', self.live)
        self.assertIn('productionShowMode', self.live)

    def test_native_auto_color_explicitly_releases_single_and_combo_ownership(self):
        self.assertIn('let overrideColorCombo: String', self.native)
        self.assertIn('@Published var liveOverrideColorCombo = "none"', self.native)
        method = self.native[
            self.native.index('func setLiveOverrideColor(_ color: String)'):
            self.native.index('func setLiveOverrideManualStrobe', self.native.index('func setLiveOverrideColor(_ color: String)'))
        ]
        self.assertIn('liveOverrideColorCombo = "none"', method)
        self.assertIn('overrideColorCombo: liveOverrideColorCombo', self.native)
        self.assertIn('remote.overrideColorCombo == pending.overrideColorCombo', self.native)

    def test_preview_map_fixture_calibration_is_backend_authoritative_and_fail_closed(self):
        for text in (
            'struct VenueFixtureCalibrationState: Decodable, Identifiable',
            'case slotID = "slotId"',
            'let physicalForward: VenueVectorState?',
            'let physicalUp: VenueVectorState?',
            'let derivedRight: VenueVectorState?',
            'struct VenueCalibrationUpdateRequest: Encodable',
            'let venueCalibration: VenueCalibrationPayload',
            'func startFixtureCalibration()',
            'private func saveSelectedFixtureCalibration()',
            'post("/api/dmx/update", body: payload',
            'struct FixtureVenueCalibrationPanel: View',
            'Label("TEST AUDIENCE CENTER", systemImage: "scope")',
            'model.isFixtureCalibrationMode',
            'Right: derived from Forward × Up',
            'struct VenueTargetTestRequest: Encodable',
            'struct VenueTargetTestResponse: Decodable',
            'case slotID = "slotId"',
            '"/api/dmx/venue-target-test"',
            'DRAFT DIAGNOSTIC • no config save • no DMX movement',
            'mountingHeightM: world.z / 100',
            'struct VenueGeometryPanel: View',
            'model.saveVenueGeometry()',
            'AUDIENCE HEIGHT',
        ):
            self.assertIn(text, self.native)
        for text in (
            'def fixture_orientation_basis(',
            'right = _vector3_normalize(_vector3_cross(forward, supplied_up))',
            '"status": "MISSING_FIXTURE_HEIGHT"',
            '"status": "MISSING_TARGET_HEIGHT"',
            '"status": "MISSING_VENUE_SCALE"',
            '"venue_calibration": None',
            '"audience_center_test": audience_test',
            '"audience_effect_migration": "VENUE_NATIVE_METERS_V1"',
            'def venue_target_test(self, payload):',
            '"physical_command_sent": False',
        ):
            self.assertIn(text, self.backend)

    def test_live_stage_motion_uses_post_render_backend_projection_not_preview_angles(self):
        for text in (
            'def rendered_motion_projection(config, rendered_final_values):',
            '"source": "rendered_final_values"',
            '"world_direction": None',
            '"physical_pan_degrees"',
            '"physical_tilt_degrees"',
            '"rendered_motion": rendered_motion',
            'renderedMotion = try container.decodeIfPresent([String: RenderedMotionState].self, forKey: .renderedMotion) ?? [:]',
            '@Published var renderedMotion: [String: RenderedMotionState] = [:]',
            'for (slotID, motion) in renderedMotion where motion.supported && motion.available && motion.status == "AVAILABLE"',
            'if let direction = state?.worldDirection',
            'Do not reapply yaw or panFlip.',
        ):
            self.assertIn(text, self.native + self.backend)

        live_beam = self.native[
            self.native.index('private func currentBeamTarget(from state: StageMotionState?)'):
            self.native.index('private func targetBeamTarget(from state: StageMotionState?)')
        ]
        self.assertIn('state?.worldDirection', live_beam)
        self.assertNotIn('worldOrigin.panFlip ? -', live_beam)

    def test_axis_mapping_v2_uses_full_directed_tilt_plane_ui_and_world_composition(self):
        for text in (
            'OBSERVED BEAM DIRECTION',
            'HORIZON FRONT',
            'HORIZON BACK',
            'FRONT / BACK are relative to the locked Pan reference',
            'measuredTiltPlaneDegrees',
            'panSweepReferenceTiltPlaneDegrees',
            'physicalTiltPlaneDegrees',
            'def axis_mapping_v2_world_direction(',
            'math.cos(tilt_radians)',
            'math.sin(tilt_radians)',
            'LEGACY_TILT_DIRECTION_REVIEW_REQUIRED',
            'measured_tilt_plane_degrees',
        ):
            self.assertIn(text, self.native + self.backend)
        tilt_wizard = self.native[
            self.native.index('private func axisV2TiltWizard'):
            self.native.index('private func normalizedCompass', self.native.index('private func axisV2TiltWizard'))
        ]
        self.assertNotIn('max(-90', tilt_wizard)
        self.assertNotIn('min(90', tilt_wizard)
        self.assertIn('normalizedDirectedTiltPlane', tilt_wizard)

    def test_dj_world_markers_and_target_preview_share_rotated_world_projection(self):
        rotated_projection = self.native[
            self.native.index('private func rotatedTopProjectionPoint'):
            self.native.index('private func unrotatedTopProjectionPoint')
        ]
        for formula in (
            'CGPoint(x: 1.0 - point.y, y: point.x)',
            'CGPoint(x: 1.0 - point.x, y: 1.0 - point.y)',
            'CGPoint(x: point.y, y: 1.0 - point.x)',
        ):
            self.assertIn(formula, rotated_projection)
        venue_overlay = self.native[
            self.native.index('struct VenueSpaceOverlay'):
            self.native.index('struct VenueTargetMarker')
        ]
        self.assertIn('worldProjectedPoint(world, projection: .top)', venue_overlay)
        self.assertIn('venueLabel("LEFT"', venue_overlay)
        self.assertIn('venueLabel("RIGHT"', venue_overlay)
        self.assertIn('venueLabel("AUDIENCE"', venue_overlay)
        self.assertIn('venueLabel("DJ / REAR"', venue_overlay)
        self.assertNotIn('venueProjectionPoint', self.native)
        self.assertIn('private func metricWorldProjectedPoint(', self.native)
        self.assertIn(
            'return metricProjectionPoint(screenHorizontal: -world.x, horizontalBounds: -StageWorld.maxX ... -StageWorld.minX, screenDown: world.y',
            self.native,
        )
        self.assertIn('private func metricProjectionCoordinates(', self.native)
        self.assertIn('Metric orthographic viewport.', self.native)
        beam = self.native[
            self.native.index('struct StageFixtureBeam'):
            self.native.index('struct TrussSegmentLine')
        ]
        self.assertIn('path.move(to: origin)', beam)
        self.assertIn('venueTargetPreview.endpoint', beam)
        self.assertIn('worldProjectedAbsoluteBeamPoint', beam)

    def test_axis_mapping_progression_is_backend_authoritative_and_save_is_primary(self):
        for text in (
            'workflowPhase',
            'workflowSampleIndex',
            'workflowSavedCount',
            'workflowMoveStatus',
            'RECOVERY / MANUAL SAMPLE',
            'AT EXACT TILT SAMPLE POSITION',
            'AT EXACT PAN SAMPLE POSITION',
            'SAVE SAMPLE',
        ):
            self.assertIn(text, self.native)
        normal_flow = self.native[
            self.native.index('private func physicalAxisMappingV2'):
            self.native.index('private func axisV2TiltFirstFlow')
        ]
        self.assertIn('mapping?.workflowPhase == "PAN"', normal_flow)
        self.assertIn('mapping?.workflowPhase == "TILT"', normal_flow)
        self.assertNotIn('.onChange(of: axisV2SelectedAxis)', normal_flow)
        for text in (
            'workflow_phase',
            'workflow_sample_index',
            '_activate_axis_mapping_v2_sample_locked',
            'axis_mapping_v2_inverse_tilt(0.0',
            'NEXT_MOVE_FAILED',
            'VALIDATION_READY',
        ):
            self.assertIn(text, self.backend)

    def test_active_backend_target_is_reconciled_on_every_state_apply(self):
        apply_method = self.native[
            self.native.index('private func apply(_ state: AppState'):
            self.native.index('private func applyVirtualDjBeatPulsePreview', self.native.index('private func apply(_ state: AppState'))
        ]
        self.assertIn('renderedMotion = state.dmx.renderedMotion', apply_method)
        self.assertIn('reconcileVenueTargetPresentation(state.dmx.venueTargetTest)', apply_method)
        reconciliation = self.native[
            self.native.index('private func reconcileVenueTargetPresentation'):
            self.native.index('private func activateVenueTargetPreview', self.native.index('private func reconcileVenueTargetPresentation'))
        ]
        self.assertIn('clearVenueTargetPreview()', reconciliation)
        self.assertIn('previewVenueTargetResultSet = authority?.resultSet', reconciliation)
        self.assertIn('startVenueTargetLeaseHeartbeat()', reconciliation)


if __name__ == "__main__":
    unittest.main()
