import SwiftUI

/// Layout tokens and formatting shared by every feature package. Colours are
/// semantic (`.primary`, `.secondary`, materials, accent), so light and dark
/// mode need no separate values.
public enum DesignSystem {
    public enum Spacing {
        public static let xs: CGFloat = 4
        public static let s: CGFloat = 8
        public static let m: CGFloat = 16
        public static let l: CGFloat = 24
        public static let xl: CGFloat = 32
    }

    public enum Radius {
        public static let card: CGFloat = 16
        public static let control: CGFloat = 10
    }

    /// Maximum width of the authentication card on regular-width screens.
    public static let authMaxWidth: CGFloat = 420

    /// Maximum width of a readable form or detail column on a pad.
    public static let contentMaxWidth: CGFloat = 640

    /// The project's tint. Replace with a brand colour when the project has
    /// one; the system accent is the safe default.
    public static let accent = Color.accentColor

    public static func price(cents: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.locale = .current
        let amount = NSDecimalNumber(value: cents).dividing(by: 100)
        return formatter.string(from: amount) ?? amount.stringValue
    }

    public static func priceInput(cents: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = .current
        formatter.usesGroupingSeparator = false
        formatter.minimumFractionDigits = 2
        formatter.maximumFractionDigits = 2
        let amount = NSDecimalNumber(value: cents).dividing(by: 100)
        return formatter.string(from: amount) ?? amount.stringValue
    }

    public static func cents(fromPriceInput input: String) -> Int? {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              let amount = Decimal(string: trimmed, locale: .current)
        else {
            return nil
        }
        var source = amount * 100
        var rounded = Decimal()
        NSDecimalRound(&rounded, &source, 0, .plain)
        let cents = NSDecimalNumber(decimal: rounded).intValue
        return cents >= 0 ? cents : nil
    }
}

/// A material card that adapts to light and dark mode.
public struct CardStyle: ViewModifier {
    public init() {}

    public func body(content: Content) -> some View {
        content
            .padding(DesignSystem.Spacing.l)
            .background(
                .regularMaterial,
                in: RoundedRectangle(
                    cornerRadius: DesignSystem.Radius.card,
                    style: .continuous
                )
            )
            .shadow(color: .black.opacity(0.06), radius: 12, y: 4)
    }
}

public extension View {
    func cardStyle() -> some View {
        modifier(CardStyle())
    }
}
