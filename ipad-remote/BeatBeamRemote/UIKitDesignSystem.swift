import UIKit

enum BBUIKitTokens {
    static let outerMargin: CGFloat = 8
    static let panelGap: CGFloat = 7
    static let panelPadding: CGFloat = 9
    static let controlGap: CGFloat = 7
    static let compactGap: CGFloat = 5
    static let headerHeight: CGFloat = 62
    static let sectionHeaderHeight: CGFloat = 18
    static let borderWidth: CGFloat = 1
    static let activeBorderWidth: CGFloat = 4
    static let cornerRadius: CGFloat = 6
    static let panelCornerRadius: CGFloat = 7
    static let minimumTouchHeight: CGFloat = 44

    static let background = UIColor(red: 0.025, green: 0.032, blue: 0.047, alpha: 1)
    static let panel = UIColor(red: 0.065, green: 0.077, blue: 0.102, alpha: 1)
    static let panelRaised = UIColor(red: 0.100, green: 0.116, blue: 0.145, alpha: 1)
    static let recessed = UIColor(red: 0.018, green: 0.023, blue: 0.034, alpha: 1)
    static let border = UIColor.white.withAlphaComponent(0.14)
    static let secondary = UIColor.white.withAlphaComponent(0.56)
    static let accent = UIColor(red: 0.10, green: 0.86, blue: 0.96, alpha: 1)
    static let warning = UIColor(red: 1.0, green: 0.62, blue: 0.08, alpha: 1)
    static let danger = UIColor(red: 0.94, green: 0.20, blue: 0.22, alpha: 1)
    static let healthy = UIColor(red: 0.20, green: 0.86, blue: 0.41, alpha: 1)

    static func labelFont(_ size: CGFloat = 12) -> UIFont {
        .monospacedSystemFont(ofSize: size, weight: .semibold)
    }

    static func valueFont(_ size: CGFloat = 15) -> UIFont {
        .systemFont(ofSize: size, weight: .semibold)
    }
}

extension UIView {
    func bbPinEdges(to view: UIView, insets: UIEdgeInsets = .zero) {
        translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: insets.left),
            trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -insets.right),
            topAnchor.constraint(equalTo: view.topAnchor, constant: insets.top),
            bottomAnchor.constraint(equalTo: view.bottomAnchor, constant: -insets.bottom),
        ])
    }
}

final class BBPanelView: UIView {
    private let titleLabel = UILabel()
    let contentView = UIView()

    init(title: String? = nil) {
        super.init(frame: .zero)
        backgroundColor = BBUIKitTokens.panel
        layer.cornerRadius = BBUIKitTokens.panelCornerRadius
        layer.borderWidth = BBUIKitTokens.borderWidth
        layer.borderColor = BBUIKitTokens.border.cgColor
        clipsToBounds = true

        titleLabel.text = title
        titleLabel.font = BBUIKitTokens.labelFont()
        titleLabel.textColor = BBUIKitTokens.secondary
        titleLabel.numberOfLines = 1
        titleLabel.setContentCompressionResistancePriority(.required, for: .vertical)
        titleLabel.setContentHuggingPriority(.required, for: .vertical)
        titleLabel.isHidden = title == nil

        let stack = UIStackView(arrangedSubviews: [titleLabel, contentView])
        stack.axis = .vertical
        stack.spacing = title == nil ? 0 : BBUIKitTokens.compactGap
        addSubview(stack)
        stack.bbPinEdges(to: self, insets: UIEdgeInsets(top: BBUIKitTokens.panelPadding, left: BBUIKitTokens.panelPadding, bottom: BBUIKitTokens.panelPadding, right: BBUIKitTokens.panelPadding))
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

final class BBSectionHeader: UIView {
    private let label = UILabel()

    init(_ title: String) {
        super.init(frame: .zero)
        label.text = title
        label.font = BBUIKitTokens.labelFont(11)
        label.textColor = BBUIKitTokens.secondary
        label.textAlignment = .center
        let left = UIView(); left.backgroundColor = BBUIKitTokens.border
        let right = UIView(); right.backgroundColor = BBUIKitTokens.border
        left.heightAnchor.constraint(equalToConstant: 1).isActive = true
        right.heightAnchor.constraint(equalToConstant: 1).isActive = true
        let stack = UIStackView(arrangedSubviews: [left, label, right])
        stack.axis = .horizontal; stack.alignment = .center; stack.spacing = 8
        addSubview(stack); stack.bbPinEdges(to: self)
        left.widthAnchor.constraint(equalTo: right.widthAnchor).isActive = true
        heightAnchor.constraint(equalToConstant: BBUIKitTokens.sectionHeaderHeight).isActive = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

class BBHardwareButton: UIButton {
    private let topHighlight = CAGradientLayer()
    var normalFaceColor = BBUIKitTokens.panelRaised { didSet { updateAppearance() } }
    var activeColor = BBUIKitTokens.accent { didSet { updateAppearance() } }
    var activeBorderColor = BBUIKitTokens.accent { didSet { updateAppearance() } }
    var isIlluminated = false { didSet { updateAppearance() } }

    init(title: String, accessibilityLabel: String? = nil) {
        super.init(frame: .zero)
        configureHardwareFace(accessibilityLabel: accessibilityLabel ?? title)
        configuration = nil
        setTitle(title, for: .normal)
    }

    init(symbol: String? = nil, accessibilityLabel: String) {
        super.init(frame: .zero)
        configureHardwareFace(accessibilityLabel: accessibilityLabel)
        configuration = nil
        if let symbol {
            setImage(UIImage(systemName: symbol), for: .normal)
            setPreferredSymbolConfiguration(.init(pointSize: 20, weight: .semibold), forImageIn: .normal)
            tintColor = .white
        }
    }

    private func configureHardwareFace(accessibilityLabel: String) {
        titleLabel?.font = BBUIKitTokens.labelFont(13)
        titleLabel?.numberOfLines = 2
        titleLabel?.textAlignment = .center
        setTitleColor(.white, for: .normal)
        setTitleColor(UIColor.white.withAlphaComponent(0.55), for: .disabled)
        layer.cornerRadius = BBUIKitTokens.cornerRadius
        layer.borderWidth = BBUIKitTokens.borderWidth
        clipsToBounds = false
        self.accessibilityLabel = accessibilityLabel
        accessibilityTraits = .button
        topHighlight.colors = [UIColor.white.withAlphaComponent(0.13).cgColor, UIColor.clear.cgColor]
        topHighlight.locations = [0, 0.48]
        topHighlight.cornerRadius = BBUIKitTokens.cornerRadius
        topHighlight.isHidden = false
        layer.insertSublayer(topHighlight, at: 0)
        addTarget(self, action: #selector(pressDown), for: [.touchDown, .touchDragEnter])
        addTarget(self, action: #selector(pressUp), for: [.touchUpInside, .touchUpOutside, .touchCancel])
        heightAnchor.constraint(greaterThanOrEqualToConstant: BBUIKitTokens.minimumTouchHeight).isActive = true
        updateAppearance()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        topHighlight.frame = bounds
    }

    @objc private func pressDown() {
        transform = CGAffineTransform(translationX: 0, y: 1).scaledBy(x: 0.986, y: 0.958)
        layer.shadowOffset = .zero
        layer.shadowRadius = 1
        alpha = 0.78
    }

    @objc private func pressUp() {
        transform = .identity
        alpha = isEnabled ? 1 : 0.48
        updateAppearance()
    }

    override var isEnabled: Bool { didSet { alpha = isEnabled ? 1 : 0.48; updateAppearance() } }

    private func updateAppearance() {
        backgroundColor = isIlluminated ? activeColor.withAlphaComponent(0.48) : normalFaceColor
        layer.borderColor = (isIlluminated ? activeBorderColor : BBUIKitTokens.border).cgColor
        layer.borderWidth = isIlluminated ? BBUIKitTokens.activeBorderWidth : BBUIKitTokens.borderWidth
        layer.shadowColor = isIlluminated ? activeColor.cgColor : UIColor.black.cgColor
        layer.shadowOpacity = isIlluminated ? 0.50 : 0.24
        layer.shadowRadius = isIlluminated ? 6 : 2
        layer.shadowOffset = CGSize(width: 0, height: 2)
        accessibilityTraits = isIlluminated ? [.button, .selected] : .button
    }
}

final class BBColorPad: BBHardwareButton {
    init(color: UIColor, accessibilityLabel: String) {
        super.init(symbol: nil, accessibilityLabel: accessibilityLabel)
        normalFaceColor = color.withAlphaComponent(0.76)
        activeColor = color == .white ? BBUIKitTokens.accent : color
        activeBorderColor = BBUIKitTokens.activeRing(for: color)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

final class BBSplitColorComboPad: UIControl {
    private let leftView = UIView()
    private let rightView = UIView()
    private let activeBorderColor: UIColor
    var isIlluminated = false { didSet { updateAppearance() } }
    var isAvailable = true { didSet { isEnabled = isAvailable; alpha = isAvailable ? 1 : 0.38 } }

    init(first: UIColor, second: UIColor, accessibilityLabel: String) {
        activeBorderColor = BBUIKitTokens.activeRing(for: first, second)
        super.init(frame: .zero)
        leftView.backgroundColor = first
        rightView.backgroundColor = second
        let halves = UIStackView(arrangedSubviews: [leftView, rightView])
        halves.axis = .horizontal; halves.distribution = .fillEqually; halves.spacing = 0
        halves.isUserInteractionEnabled = false
        leftView.isUserInteractionEnabled = false
        rightView.isUserInteractionEnabled = false
        addSubview(halves); halves.bbPinEdges(to: self)
        let contrastScrim = UIView()
        contrastScrim.backgroundColor = UIColor.black.withAlphaComponent(0.16)
        contrastScrim.isUserInteractionEnabled = false
        addSubview(contrastScrim); contrastScrim.bbPinEdges(to: self)
        layer.cornerRadius = BBUIKitTokens.cornerRadius
        layer.borderWidth = BBUIKitTokens.borderWidth
        layer.borderColor = BBUIKitTokens.border.cgColor
        clipsToBounds = true
        self.accessibilityLabel = accessibilityLabel
        accessibilityTraits = .button
        heightAnchor.constraint(greaterThanOrEqualToConstant: BBUIKitTokens.minimumTouchHeight).isActive = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override var isHighlighted: Bool { didSet { transform = isHighlighted ? CGAffineTransform(scaleX: 0.985, y: 0.96) : .identity; alpha = isHighlighted ? 0.72 : (isAvailable ? 1 : 0.38) } }

    private func updateAppearance() {
        layer.borderColor = (isIlluminated ? activeBorderColor : BBUIKitTokens.border).cgColor
        layer.borderWidth = isIlluminated ? BBUIKitTokens.activeBorderWidth : BBUIKitTokens.borderWidth
        accessibilityTraits = isIlluminated ? [.button, .selected] : .button
    }
}

final class BBLabeledControl: UIView {
    let control: UIView

    init(label: String, detail: String? = nil, control: UIView, compact: Bool = false) {
        self.control = control
        super.init(frame: .zero)

        let title = UILabel()
        title.text = label.uppercased()
        title.font = BBUIKitTokens.labelFont(compact ? 8.5 : 10)
        title.textColor = BBUIKitTokens.secondary
        title.textAlignment = .center
        title.adjustsFontSizeToFitWidth = true
        title.minimumScaleFactor = 0.62
        title.numberOfLines = 1
        title.isUserInteractionEnabled = false
        title.setContentCompressionResistancePriority(.required, for: .vertical)

        let labelStack = UIStackView(arrangedSubviews: [title])
        labelStack.axis = .vertical
        labelStack.spacing = 0
        labelStack.isUserInteractionEnabled = false
        if let detail {
            let status = UILabel()
            status.text = detail.uppercased()
            status.font = BBUIKitTokens.labelFont(7.5)
            status.textColor = BBUIKitTokens.warning
            status.textAlignment = .center
            status.adjustsFontSizeToFitWidth = true
            status.minimumScaleFactor = 0.65
            status.isUserInteractionEnabled = false
            labelStack.addArrangedSubview(status)
        }

        let stack = UIStackView(arrangedSubviews: [labelStack, control])
        stack.axis = .vertical
        stack.spacing = compact ? 3 : 4
        addSubview(stack)
        stack.bbPinEdges(to: self)
        control.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? {
        let controlPoint = convert(point, to: control)
        guard control.bounds.contains(controlPoint) else { return nil }
        return control.hitTest(controlPoint, with: event)
    }
}

final class BBOneShotProgressButton: BBHardwareButton {
    private let progressFill = CALayer()
    private var remainingFraction: CGFloat = 0

    init(symbol: String, accessibilityLabel: String) {
        super.init(symbol: symbol, accessibilityLabel: accessibilityLabel)
        progressFill.backgroundColor = BBUIKitTokens.accent.withAlphaComponent(0.62).cgColor
        progressFill.cornerRadius = BBUIKitTokens.cornerRadius
        progressFill.masksToBounds = true
        progressFill.isHidden = true
        // Keep the fill above the hardware face and its highlight. UIButton's
        // label/image subviews remain above this layer, so the control glyph
        // stays readable while the authoritative lifetime drains underneath it.
        layer.addSublayer(progressFill)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        let height = bounds.height * remainingFraction
        progressFill.frame = CGRect(x: 0, y: bounds.height - height, width: bounds.width, height: height)
        progressFill.cornerRadius = min(BBUIKitTokens.cornerRadius, height / 2)
    }

    func setRemainingFraction(_ value: Double?) {
        remainingFraction = CGFloat(min(max(value ?? 0, 0), 1))
        progressFill.isHidden = remainingFraction <= 0
        setNeedsLayout()
        accessibilityValue = remainingFraction > 0 ? "\(Int((remainingFraction * 100).rounded())) percent remaining" : nil
    }
}

extension BBUIKitTokens {
    static func activeRing(for color: UIColor, _ secondary: UIColor? = nil) -> UIColor {
        let colors = [color] + (secondary.map { [$0] } ?? [])
        let allBright = colors.allSatisfy { value in
            var red: CGFloat = 0; var green: CGFloat = 0; var blue: CGFloat = 0; var alpha: CGFloat = 0
            guard value.getRed(&red, green: &green, blue: &blue, alpha: &alpha) else { return false }
            return (red * 0.299 + green * 0.587 + blue * 0.114) > 0.68
        }
        return allBright ? UIColor.black.withAlphaComponent(0.88) : UIColor.white
    }
}

final class BBStatusIndicator: UIView {
    private let dot = UIView()
    private let titleLabel = UILabel()
    private let valueLabel = UILabel()

    init(title: String) {
        super.init(frame: .zero)
        dot.layer.cornerRadius = 4
        dot.widthAnchor.constraint(equalToConstant: 8).isActive = true
        dot.heightAnchor.constraint(equalToConstant: 8).isActive = true
        titleLabel.text = title
        titleLabel.font = BBUIKitTokens.labelFont(10)
        titleLabel.textColor = BBUIKitTokens.secondary
        valueLabel.font = BBUIKitTokens.labelFont(11)
        valueLabel.textColor = .white
        valueLabel.textAlignment = .right
        valueLabel.adjustsFontSizeToFitWidth = true
        valueLabel.minimumScaleFactor = 0.7
        let stack = UIStackView(arrangedSubviews: [dot, titleLabel, valueLabel])
        stack.axis = .horizontal; stack.alignment = .center; stack.spacing = 7
        addSubview(stack); stack.bbPinEdges(to: self, insets: UIEdgeInsets(top: 6, left: 7, bottom: 6, right: 7))
        backgroundColor = UIColor.white.withAlphaComponent(0.035)
        layer.cornerRadius = 4
        layer.borderWidth = 1
        layer.borderColor = BBUIKitTokens.border.cgColor
        heightAnchor.constraint(greaterThanOrEqualToConstant: 35).isActive = true
        isAccessibilityElement = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func set(value: String, healthy: Bool, warning: Bool = false) {
        valueLabel.text = value.uppercased()
        let color = healthy ? BBUIKitTokens.healthy : (warning ? BBUIKitTokens.warning : BBUIKitTokens.danger)
        valueLabel.textColor = color
        dot.backgroundColor = color
        dot.layer.shadowColor = color.cgColor; dot.layer.shadowOpacity = 0.75; dot.layer.shadowRadius = 4
        accessibilityLabel = "\(titleLabel.text ?? "Status"), \(value)"
    }
}

final class BBValueReadout: UIView {
    private let titleLabel = UILabel()
    private let valueLabel = UILabel()

    init(title: String) {
        super.init(frame: .zero)
        titleLabel.text = title
        titleLabel.font = BBUIKitTokens.labelFont(10)
        titleLabel.textColor = BBUIKitTokens.secondary
        valueLabel.font = BBUIKitTokens.valueFont(15)
        valueLabel.textColor = .white
        valueLabel.adjustsFontSizeToFitWidth = true
        valueLabel.minimumScaleFactor = 0.65
        valueLabel.numberOfLines = 1
        let stack = UIStackView(arrangedSubviews: [titleLabel, valueLabel])
        stack.axis = .vertical; stack.spacing = 2
        addSubview(stack); stack.bbPinEdges(to: self)
        isAccessibilityElement = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func set(_ value: String, color: UIColor = .white) {
        valueLabel.text = value
        valueLabel.textColor = color
        accessibilityLabel = "\(titleLabel.text ?? "Value"), \(value)"
    }
}

class BBVerticalHardwareFader: UIControl {
    private let faceplate = BBBrushedMetalFaceplate()
    private let rail = BBChannelFaderSlot()
    private let scale = BBChannelFaderScale()
    private let cap = BBChannelFaderCap()
    private let valueLabel = UILabel()
    private var scaleLabels: [UILabel] = []
    private let scaleTitles: [String]
    private let discreteSteps: Int?
    private(set) var normalizedValue: CGFloat = 0
    private let capSize = CGSize(width: 36, height: 76)

    init(scaleTitles: [String], discreteSteps: Int?, accessibilityName: String) {
        self.scaleTitles = scaleTitles
        self.discreteSteps = discreteSteps
        super.init(frame: .zero)
        backgroundColor = .clear
        layer.cornerRadius = BBUIKitTokens.cornerRadius
        layer.borderWidth = 1
        layer.borderColor = BBUIKitTokens.border.cgColor
        clipsToBounds = true

        faceplate.isUserInteractionEnabled = false
        addSubview(faceplate)
        faceplate.translatesAutoresizingMaskIntoConstraints = false

        rail.isUserInteractionEnabled = false
        addSubview(rail)
        rail.translatesAutoresizingMaskIntoConstraints = false

        scale.isUserInteractionEnabled = false
        scale.majorCount = max(2, scaleTitles.count)
        addSubview(scale)
        scale.translatesAutoresizingMaskIntoConstraints = false

        cap.isUserInteractionEnabled = false
        addSubview(cap)

        for title in scaleTitles {
            let label = UILabel(); label.text = title; label.font = BBUIKitTokens.labelFont(10); label.textColor = BBUIKitTokens.secondary
            label.textAlignment = .right
            label.isUserInteractionEnabled = false
            addSubview(label)
            scaleLabels.append(label)
        }

        valueLabel.font = BBUIKitTokens.labelFont(11)
        valueLabel.textColor = BBUIKitTokens.warning
        valueLabel.textAlignment = .center
        addSubview(valueLabel)
        valueLabel.translatesAutoresizingMaskIntoConstraints = false

        NSLayoutConstraint.activate([
            // The broad UIControl remains the touch target; only this centred
            // channel is the narrow visible hardware slot.
            rail.centerXAnchor.constraint(equalTo: centerXAnchor, constant: 16), rail.widthAnchor.constraint(equalToConstant: 5),
            rail.topAnchor.constraint(equalTo: topAnchor, constant: 28), rail.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -14),
            faceplate.centerXAnchor.constraint(equalTo: rail.centerXAnchor), faceplate.widthAnchor.constraint(equalToConstant: 54),
            faceplate.topAnchor.constraint(equalTo: topAnchor, constant: 22), faceplate.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -8),
            scale.leadingAnchor.constraint(equalTo: rail.trailingAnchor, constant: 4), scale.widthAnchor.constraint(equalToConstant: 9),
            scale.topAnchor.constraint(equalTo: rail.topAnchor), scale.bottomAnchor.constraint(equalTo: rail.bottomAnchor),
            valueLabel.topAnchor.constraint(equalTo: topAnchor, constant: 7), valueLabel.centerXAnchor.constraint(equalTo: rail.centerXAnchor),
        ])
        isAccessibilityElement = true
        accessibilityLabel = accessibilityName
        accessibilityTraits = .adjustable
        setNormalizedValue(0, sendEvent: false)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        // Keep the cap fully in the slot at the two endpoints. The printed
        // level labels use this identical visual centre, so every label sits
        // exactly beside the cap's white reference line in its own position.
        let capCenterY = visualCenterY(for: normalizedValue, height: bounds.height)
        cap.frame = CGRect(x: bounds.midX + 16 - capSize.width / 2, y: capCenterY - capSize.height / 2, width: capSize.width, height: capSize.height)
        for (index, label) in scaleLabels.enumerated() {
            let denominator = CGFloat(max(1, scaleLabels.count - 1))
            let labelValue = 1 - CGFloat(index) / denominator
            let labelY = visualCenterY(for: labelValue, height: bounds.height)
            // Labels sit beside their major tick, not over the channel panel.
            label.frame = CGRect(x: 0, y: labelY - 7, width: 30, height: 14)
        }
    }

    private func normalizedValue(for y: CGFloat, height: CGFloat) -> CGFloat {
        let top: CGFloat = 28
        let bottom = max(top + 1, height - 14)
        let topCenter = top + capSize.height / 2
        let bottomCenter = bottom - capSize.height / 2
        let clamped = min(max(y, topCenter), bottomCenter)
        return 1 - ((clamped - topCenter) / max(1, bottomCenter - topCenter))
    }

    func setNormalizedValue(_ rawValue: CGFloat, sendEvent: Bool) {
        var value = min(1, max(0, rawValue))
        if let steps = discreteSteps, steps > 1 {
            value = (value * CGFloat(steps - 1)).rounded() / CGFloat(steps - 1)
        }
        guard abs(normalizedValue - value) > 0.0001 else { return }
        normalizedValue = value
        didChangeNormalizedValue()
        setNeedsLayout()
        if sendEvent { sendActions(for: .valueChanged) }
    }

    func didChangeNormalizedValue() { }

    func setDisplayText(_ text: String) {
        valueLabel.text = text
        accessibilityValue = text
    }

    private func visualCenterY(for value: CGFloat, height: CGFloat) -> CGFloat {
        let trackTop: CGFloat = 28
        let trackBottom = max(trackTop + capSize.height, height - 14)
        let topCenter = trackTop + capSize.height / 2
        let bottomCenter = trackBottom - capSize.height / 2
        return bottomCenter - value * (bottomCenter - topCenter)
    }

    private func update(with touch: UITouch) {
        setNormalizedValue(normalizedValue(for: touch.location(in: self).y, height: bounds.height), sendEvent: true)
    }

    override func beginTracking(_ touch: UITouch, with event: UIEvent?) -> Bool { cap.isPressed = true; update(with: touch); return true }
    override func continueTracking(_ touch: UITouch, with event: UIEvent?) -> Bool { update(with: touch); return true }
    override func endTracking(_ touch: UITouch?, with event: UIEvent?) { cap.isPressed = false; if let touch { update(with: touch) } }
    override func cancelTracking(with event: UIEvent?) { cap.isPressed = false }

    override func accessibilityIncrement() {
        let step = discreteSteps.map { 1 / CGFloat(max(1, $0 - 1)) } ?? 0.05
        setNormalizedValue(normalizedValue + step, sendEvent: true)
    }
    override func accessibilityDecrement() {
        let step = discreteSteps.map { 1 / CGFloat(max(1, $0 - 1)) } ?? 0.05
        setNormalizedValue(normalizedValue - step, sendEvent: true)
    }
}

final class BBVerticalEnergyFader: BBVerticalHardwareFader {
    enum Level: Int, CaseIterable { case automatic = 0, low, mid, high
        var id: String { ["none", "low", "mid", "high"][rawValue] }
        var label: String { ["AUTO", "LOW", "MID", "HIGH"][rawValue] }
    }
    var level: Level { Level(rawValue: Int((normalizedValue * 3).rounded())) ?? .automatic }

    init() {
        super.init(scaleTitles: ["HIGH", "MID", "LOW", "AUTO"], discreteSteps: 4, accessibilityName: "Energy override vertical fader")
        setDisplayText(level.label)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func didChangeNormalizedValue() { setDisplayText(level.label) }
    func set(level: Level, sendEvent: Bool) { setNormalizedValue(CGFloat(level.rawValue) / 3, sendEvent: sendEvent) }
}

final class BBVerticalFxSpeedFader: BBVerticalHardwareFader {
    enum Level: Int, CaseIterable { case automatic = 0, slow, mid, fast
        var id: String { ["auto", "slow", "mid", "fast"][rawValue] }
        var label: String { ["AUTO", "SLOW", "MID", "FAST"][rawValue] }
    }
    var level: Level { Level(rawValue: Int((normalizedValue * 3).rounded())) ?? .automatic }
    private var resolved = "MID"

    init() {
        super.init(scaleTitles: ["FAST", "MID", "SLOW", "AUTO"], discreteSteps: 4, accessibilityName: "FX Speed vertical fader")
        setDisplayText(level.label)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func didChangeNormalizedValue() {
        setDisplayText(level == .automatic ? "AUTO→\(resolved)" : level.label)
    }
    func set(level: Level, resolved: String, sendEvent: Bool) {
        self.resolved = resolved.uppercased()
        setNormalizedValue(CGFloat(level.rawValue) / 3, sendEvent: sendEvent)
        didChangeNormalizedValue()
    }
}

final class BBVerticalMasterDimmerFader: BBVerticalHardwareFader {
    var value: Double { Double(normalizedValue) }

    init() {
        super.init(scaleTitles: ["100", "75", "50", "25", "0"], discreteSteps: nil, accessibilityName: "Master Dimmer vertical fader")
        set(value: 1, sendEvent: false)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func didChangeNormalizedValue() { setDisplayText("\(Int((value * 100).rounded()))%") }
    func set(value: Double, sendEvent: Bool) { setNormalizedValue(CGFloat(min(1, max(0, value))), sendEvent: sendEvent) }
}

private final class BBBrushedMetalFaceplate: UIView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        layer.cornerRadius = 5
        layer.borderWidth = 1
        layer.borderColor = UIColor.white.withAlphaComponent(0.16).cgColor
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        let colors = [
            UIColor(red: 0.42, green: 0.44, blue: 0.47, alpha: 1).cgColor,
            UIColor(red: 0.32, green: 0.34, blue: 0.38, alpha: 1).cgColor,
            UIColor(red: 0.23, green: 0.25, blue: 0.29, alpha: 1).cgColor,
        ] as CFArray
        let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 0.52, 1])!
        context.drawLinearGradient(gradient, start: CGPoint(x: rect.midX, y: rect.minY), end: CGPoint(x: rect.midX, y: rect.maxY), options: [])
        // Fixed, sparse lines read as fine horizontal brushing without creating
        // per-drag noise or a repeating image asset.
        for index in stride(from: 4, through: Int(rect.height) - 4, by: 3) {
            let alpha: CGFloat = index.isMultiple(of: 9) ? 0.045 : 0.020
            context.setStrokeColor(UIColor.white.withAlphaComponent(alpha).cgColor)
            context.setLineWidth(0.5)
            context.move(to: CGPoint(x: 5, y: CGFloat(index)))
            context.addLine(to: CGPoint(x: rect.width - 5, y: CGFloat(index)))
            context.strokePath()
        }
    }
}

private final class BBChannelFaderSlot: UIView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = UIColor.black.withAlphaComponent(0.76)
        layer.cornerRadius = 5
        layer.borderWidth = 1
        layer.borderColor = UIColor.white.withAlphaComponent(0.22).cgColor
        layer.shadowColor = UIColor.black.cgColor
        layer.shadowOpacity = 0.82
        layer.shadowRadius = 2
        layer.shadowOffset = CGSize(width: 0, height: 1)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

private final class BBChannelFaderScale: UIView {
    var majorCount = 4 { didSet { setNeedsDisplay() } }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext(), rect.height > 1 else { return }
        let intervals = max(1, majorCount - 1)
        let minorSteps = intervals * 4
        let majorPositions = (0...intervals).map { CGFloat($0) / CGFloat(intervals) }
        for step in 0...minorSteps {
            let fraction = CGFloat(step) / CGFloat(minorSteps)
            let y = rect.height - (fraction * rect.height)
            let isMajor = majorPositions.contains { abs($0 - fraction) < 0.001 }
            let length: CGFloat = isMajor ? 8 : 4
            context.setStrokeColor(UIColor.white.withAlphaComponent(isMajor ? 0.32 : 0.14).cgColor)
            context.setLineWidth(isMajor ? 1 : 0.5)
            context.move(to: CGPoint(x: rect.width - length, y: y))
            context.addLine(to: CGPoint(x: rect.width, y: y))
            context.strokePath()
        }
    }
}

private final class BBChannelFaderCap: UIView {
    private let lighting = CAGradientLayer()
    var isPressed = false { didSet { updatePressAppearance() } }

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = UIColor(red: 0.20, green: 0.22, blue: 0.25, alpha: 1)
        layer.cornerRadius = 4
        layer.borderWidth = 1
        layer.borderColor = UIColor.white.withAlphaComponent(0.34).cgColor
        layer.shadowColor = UIColor.black.cgColor
        layer.shadowOpacity = 0.75
        layer.shadowRadius = 3
        layer.shadowOffset = CGSize(width: 0, height: 2)
        lighting.colors = [UIColor.white.withAlphaComponent(0.25).cgColor, UIColor.clear.cgColor, UIColor.black.withAlphaComponent(0.38).cgColor]
        lighting.locations = [0, 0.42, 1]
        lighting.startPoint = CGPoint(x: 0.5, y: 0)
        lighting.endPoint = CGPoint(x: 0.5, y: 1)
        lighting.cornerRadius = 4
        layer.addSublayer(lighting)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        lighting.frame = bounds
    }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        let ribX: CGFloat = 7
        for y in stride(from: CGFloat(7), through: rect.height - 6, by: 6) {
            context.setStrokeColor(UIColor.black.withAlphaComponent(0.50).cgColor)
            context.setLineWidth(1)
            context.move(to: CGPoint(x: ribX, y: y))
            context.addLine(to: CGPoint(x: rect.width - ribX, y: y))
            context.strokePath()
            context.setStrokeColor(UIColor.white.withAlphaComponent(0.14).cgColor)
            context.move(to: CGPoint(x: ribX, y: y - 1))
            context.addLine(to: CGPoint(x: rect.width - ribX, y: y - 1))
            context.strokePath()
        }
        context.setStrokeColor(UIColor.white.withAlphaComponent(0.44).cgColor)
        context.setLineWidth(1)
        context.move(to: CGPoint(x: 5, y: rect.midY))
        context.addLine(to: CGPoint(x: rect.width - 5, y: rect.midY))
        context.strokePath()
    }

    private func updatePressAppearance() {
        layer.shadowOpacity = isPressed ? 0.36 : 0.75
        layer.shadowOffset = isPressed ? CGSize(width: 0, height: 1) : CGSize(width: 0, height: 2)
        layer.borderColor = (isPressed ? BBUIKitTokens.accent.withAlphaComponent(0.88) : UIColor.white.withAlphaComponent(0.34)).cgColor
        alpha = isPressed ? 0.94 : 1
    }
}

func bbColor(_ id: String) -> UIColor {
    switch id.lowercased() {
    case "red": return .systemRed
    case "yellow": return .systemYellow
    case "green": return UIColor(red: 0.10, green: 0.76, blue: 0.30, alpha: 1)
    case "lime": return UIColor(red: 0.43, green: 0.91, blue: 0.08, alpha: 1)
    case "cyan": return .systemCyan
    case "blue": return .systemBlue
    case "purple": return .systemPurple
    case "pink": return .systemPink
    case "orange": return .systemOrange
    case "white": return .white
    case "rainbow": return BBUIKitTokens.accent
    default: return .systemGray
    }
}
