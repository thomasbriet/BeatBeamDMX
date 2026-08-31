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
    static let activeBorderWidth: CGFloat = 2
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
    var normalFaceColor = BBUIKitTokens.panelRaised { didSet { updateAppearance() } }
    var activeColor = BBUIKitTokens.accent { didSet { updateAppearance() } }
    var isIlluminated = false { didSet { updateAppearance() } }

    init(title: String, accessibilityLabel: String? = nil) {
        super.init(frame: .zero)
        configuration = nil
        setTitle(title, for: .normal)
        titleLabel?.font = BBUIKitTokens.labelFont(13)
        titleLabel?.numberOfLines = 2
        titleLabel?.textAlignment = .center
        setTitleColor(.white, for: .normal)
        setTitleColor(UIColor.white.withAlphaComponent(0.55), for: .disabled)
        layer.cornerRadius = BBUIKitTokens.cornerRadius
        layer.borderWidth = BBUIKitTokens.borderWidth
        clipsToBounds = false
        self.accessibilityLabel = accessibilityLabel ?? title
        accessibilityTraits = .button
        addTarget(self, action: #selector(pressDown), for: [.touchDown, .touchDragEnter])
        addTarget(self, action: #selector(pressUp), for: [.touchUpInside, .touchUpOutside, .touchCancel, .touchDragExit])
        heightAnchor.constraint(greaterThanOrEqualToConstant: BBUIKitTokens.minimumTouchHeight).isActive = true
        updateAppearance()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    @objc private func pressDown() { transform = CGAffineTransform(scaleX: 0.985, y: 0.965); alpha = 0.72 }
    @objc private func pressUp() { transform = .identity; alpha = isEnabled ? 1 : 0.48 }

    override var isEnabled: Bool { didSet { alpha = isEnabled ? 1 : 0.48; updateAppearance() } }

    private func updateAppearance() {
        backgroundColor = isIlluminated ? activeColor.withAlphaComponent(0.48) : normalFaceColor
        layer.borderColor = (isIlluminated ? activeColor : BBUIKitTokens.border).cgColor
        layer.borderWidth = isIlluminated ? BBUIKitTokens.activeBorderWidth : BBUIKitTokens.borderWidth
        layer.shadowColor = isIlluminated ? activeColor.cgColor : UIColor.black.cgColor
        layer.shadowOpacity = isIlluminated ? 0.50 : 0.24
        layer.shadowRadius = isIlluminated ? 6 : 2
        layer.shadowOffset = CGSize(width: 0, height: 2)
        accessibilityTraits = isIlluminated ? [.button, .selected] : .button
    }
}

final class BBColorPad: BBHardwareButton {
    private let padColor: UIColor

    init(title: String, color: UIColor) {
        padColor = color
        super.init(title: title, accessibilityLabel: "Color \(title)")
        normalFaceColor = color.withAlphaComponent(0.76)
        activeColor = color == .white ? BBUIKitTokens.accent : color
        setTitleColor((color == .yellow || color == .white) ? .black : .white, for: .normal)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

final class BBSplitColorComboPad: UIControl {
    private let leftView = UIView()
    private let rightView = UIView()
    private let titleLabel = UILabel()
    var isIlluminated = false { didSet { updateAppearance() } }
    var isAvailable = true { didSet { isEnabled = isAvailable; alpha = isAvailable ? 1 : 0.38 } }

    init(title: String, first: UIColor, second: UIColor) {
        super.init(frame: .zero)
        leftView.backgroundColor = first
        rightView.backgroundColor = second
        let halves = UIStackView(arrangedSubviews: [leftView, rightView])
        halves.axis = .horizontal; halves.distribution = .fillEqually; halves.spacing = 0
        addSubview(halves); halves.bbPinEdges(to: self)
        let contrastScrim = UIView()
        contrastScrim.backgroundColor = UIColor.black.withAlphaComponent(0.16)
        contrastScrim.isUserInteractionEnabled = false
        addSubview(contrastScrim); contrastScrim.bbPinEdges(to: self)
        titleLabel.text = title
        titleLabel.font = BBUIKitTokens.labelFont(11)
        titleLabel.textColor = .white
        titleLabel.textAlignment = .center
        titleLabel.adjustsFontSizeToFitWidth = true
        titleLabel.minimumScaleFactor = 0.68
        titleLabel.layer.shadowColor = UIColor.black.cgColor
        titleLabel.layer.shadowOpacity = 0.9
        titleLabel.layer.shadowRadius = 2
        addSubview(titleLabel); titleLabel.bbPinEdges(to: self, insets: UIEdgeInsets(top: 2, left: 4, bottom: 2, right: 4))
        layer.cornerRadius = BBUIKitTokens.cornerRadius
        layer.borderWidth = BBUIKitTokens.borderWidth
        layer.borderColor = BBUIKitTokens.border.cgColor
        clipsToBounds = true
        accessibilityLabel = "Color combination \(title)"
        accessibilityTraits = .button
        heightAnchor.constraint(greaterThanOrEqualToConstant: BBUIKitTokens.minimumTouchHeight).isActive = true
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override var isHighlighted: Bool { didSet { transform = isHighlighted ? CGAffineTransform(scaleX: 0.985, y: 0.96) : .identity; alpha = isHighlighted ? 0.72 : (isAvailable ? 1 : 0.38) } }

    private func updateAppearance() {
        layer.borderColor = (isIlluminated ? UIColor.white : BBUIKitTokens.border).cgColor
        layer.borderWidth = isIlluminated ? 3 : BBUIKitTokens.borderWidth
        accessibilityTraits = isIlluminated ? [.button, .selected] : .button
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

final class BBVerticalEnergyFader: UIControl {
    enum Level: Int, CaseIterable { case automatic = 0, low, mid, high
        var id: String { ["none", "low", "mid", "high"][rawValue] }
        var label: String { ["AUTO", "LOW", "MID", "HIGH"][rawValue] }
    }

    private let rail = UIView()
    private let cap = UIView()
    private let valueLabel = UILabel()
    private let labels = UIStackView()
    private(set) var level: Level = .automatic

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = BBUIKitTokens.recessed
        layer.cornerRadius = BBUIKitTokens.cornerRadius
        layer.borderWidth = 1
        layer.borderColor = BBUIKitTokens.border.cgColor

        rail.backgroundColor = BBUIKitTokens.warning.withAlphaComponent(0.30)
        rail.layer.cornerRadius = 4
        addSubview(rail)
        rail.translatesAutoresizingMaskIntoConstraints = false

        cap.backgroundColor = BBUIKitTokens.warning
        cap.layer.cornerRadius = 18
        cap.layer.borderWidth = 2
        cap.layer.borderColor = UIColor.white.withAlphaComponent(0.75).cgColor
        cap.layer.shadowColor = UIColor.black.cgColor; cap.layer.shadowOpacity = 0.6; cap.layer.shadowRadius = 3; cap.layer.shadowOffset = CGSize(width: 0, height: 2)
        addSubview(cap)

        labels.axis = .vertical; labels.distribution = .equalSpacing
        for title in ["HIGH", "MID", "LOW", "AUTO"] {
            let label = UILabel(); label.text = title; label.font = BBUIKitTokens.labelFont(10); label.textColor = BBUIKitTokens.secondary
            labels.addArrangedSubview(label)
        }
        addSubview(labels)
        labels.translatesAutoresizingMaskIntoConstraints = false

        valueLabel.font = BBUIKitTokens.labelFont(11)
        valueLabel.textColor = BBUIKitTokens.warning
        valueLabel.textAlignment = .center
        addSubview(valueLabel)
        valueLabel.translatesAutoresizingMaskIntoConstraints = false

        NSLayoutConstraint.activate([
            rail.centerXAnchor.constraint(equalTo: centerXAnchor, constant: 16), rail.widthAnchor.constraint(equalToConstant: 8),
            rail.topAnchor.constraint(equalTo: topAnchor, constant: 28), rail.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -14),
            labels.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 9), labels.topAnchor.constraint(equalTo: rail.topAnchor),
            labels.bottomAnchor.constraint(equalTo: rail.bottomAnchor), labels.widthAnchor.constraint(equalToConstant: 42),
            valueLabel.topAnchor.constraint(equalTo: topAnchor, constant: 7), valueLabel.centerXAnchor.constraint(equalTo: rail.centerXAnchor),
        ])
        isAccessibilityElement = true
        accessibilityLabel = "Energy override vertical fader"
        accessibilityTraits = .adjustable
        set(level: .automatic, sendEvent: false)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        let y = yPosition(for: level, height: bounds.height)
        cap.frame = CGRect(x: bounds.midX + 16 - 18, y: y - 18, width: 36, height: 36)
    }

    static func level(for y: CGFloat, height: CGFloat) -> Level {
        let top: CGFloat = 28
        let bottom = max(top + 1, height - 14)
        let clamped = min(max(y, top), bottom)
        let normalized = 1 - ((clamped - top) / (bottom - top))
        return Level(rawValue: Int((normalized * 3).rounded())) ?? .automatic
    }

    func set(level: Level, sendEvent: Bool) {
        guard self.level != level || !sendEvent else { return }
        self.level = level
        valueLabel.text = level.label
        accessibilityValue = level.label
        setNeedsLayout()
        if sendEvent { sendActions(for: .valueChanged) }
    }

    private func yPosition(for level: Level, height: CGFloat) -> CGFloat {
        let top: CGFloat = 28
        let bottom = max(top + 1, height - 14)
        return bottom - CGFloat(level.rawValue) / 3 * (bottom - top)
    }

    private func update(with touch: UITouch) {
        set(level: Self.level(for: touch.location(in: self).y, height: bounds.height), sendEvent: true)
    }

    override func beginTracking(_ touch: UITouch, with event: UIEvent?) -> Bool { update(with: touch); return true }
    override func continueTracking(_ touch: UITouch, with event: UIEvent?) -> Bool { update(with: touch); return true }
    override func endTracking(_ touch: UITouch?, with event: UIEvent?) { if let touch { update(with: touch) } }
    override func cancelTracking(with event: UIEvent?) {}

    override func accessibilityIncrement() { set(level: Level(rawValue: min(3, level.rawValue + 1)) ?? .high, sendEvent: true) }
    override func accessibilityDecrement() { set(level: Level(rawValue: max(0, level.rawValue - 1)) ?? .automatic, sendEvent: true) }
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
