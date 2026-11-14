import SwiftUI

public enum LayoutMode {
    case compact
    case regular

    public init(sizeClass: UserInterfaceSizeClass?) {
        self = sizeClass == .regular ? .regular : .compact
    }
}

/// A stack that is horizontal on a pad and vertical on a phone.
public struct AdaptiveStack<Content: View>: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private let horizontalAlignment: HorizontalAlignment
    private let verticalAlignment: VerticalAlignment
    private let spacing: CGFloat?
    private let content: () -> Content

    public init(
        horizontalAlignment: HorizontalAlignment = .center,
        verticalAlignment: VerticalAlignment = .center,
        spacing: CGFloat? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.horizontalAlignment = horizontalAlignment
        self.verticalAlignment = verticalAlignment
        self.spacing = spacing
        self.content = content
    }

    public var body: some View {
        if LayoutMode(sizeClass: horizontalSizeClass) == .regular {
            HStack(alignment: verticalAlignment, spacing: spacing, content: content)
        } else {
            VStack(alignment: horizontalAlignment, spacing: spacing, content: content)
        }
    }
}

/// A centered card for forms. On a pad it stops growing at `maxWidth`; on a
/// phone it fills the width. The scroll view keeps the content reachable when
/// the keyboard appears.
public struct CenteredCard<Content: View>: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private let maxWidth: CGFloat
    private let content: () -> Content

    public init(
        maxWidth: CGFloat = DesignSystem.authMaxWidth,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.maxWidth = maxWidth
        self.content = content
    }

    public var body: some View {
        ScrollView {
            content()
                .frame(
                    maxWidth: LayoutMode(sizeClass: horizontalSizeClass) == .regular
                        ? maxWidth
                        : .infinity
                )
                .cardStyle()
                .padding(.horizontal, DesignSystem.Spacing.m)
                .padding(.vertical, DesignSystem.Spacing.xl)
                .frame(maxWidth: .infinity)
        }
        .background(.background)
    }
}

/// Caps a form or detail view at a readable width on pads and lets it fill a
/// phone.
public struct ContentColumn<Content: View>: View {
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private let maxWidth: CGFloat
    private let content: () -> Content

    public init(
        maxWidth: CGFloat = DesignSystem.contentMaxWidth,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.maxWidth = maxWidth
        self.content = content
    }

    public var body: some View {
        content()
            .frame(
                maxWidth: LayoutMode(sizeClass: horizontalSizeClass) == .regular
                    ? maxWidth
                    : .infinity
            )
            .frame(maxWidth: .infinity)
    }
}
