import SwiftUI

/// The project's iOS UI seam. Feature packages read this from the SwiftUI
/// environment; replace a closure (or the reference view) without changing
/// feature data flow. The chat closures are ready for the chat-first root; the
/// reference implementation is intentionally simple.
public struct AppComponents {
    public var productRow: (Product) -> AnyView
    public var emptyState: (String, String?) -> AnyView
    public var primaryButton: (String, String, @escaping () -> Void) -> AnyView
    public var chatMessage: (Bool, String) -> AnyView
    public var composer: (
        Binding<String>, Bool, @escaping () -> Void, @escaping () -> Void
    ) -> AnyView
    public var toolCall: (String, String) -> AnyView
    public var feedbackButtons: (Int?, @escaping (Int) -> Void) -> AnyView

    public init(
        productRow: @escaping (Product) -> AnyView,
        emptyState: @escaping (String, String?) -> AnyView,
        primaryButton: @escaping (String, String, @escaping () -> Void) -> AnyView,
        chatMessage: @escaping (Bool, String) -> AnyView,
        composer: @escaping (
            Binding<String>, Bool, @escaping () -> Void, @escaping () -> Void
        ) -> AnyView,
        toolCall: @escaping (String, String) -> AnyView,
        feedbackButtons: @escaping (Int?, @escaping (Int) -> Void) -> AnyView
    ) {
        self.productRow = productRow
        self.emptyState = emptyState
        self.primaryButton = primaryButton
        self.chatMessage = chatMessage
        self.composer = composer
        self.toolCall = toolCall
        self.feedbackButtons = feedbackButtons
    }

    public static let reference = AppComponents(
        productRow: { product in
            AnyView(ReferenceProductRow(product: product))
        },
        emptyState: { title, message in
            AnyView(ReferenceEmptyState(title: title, message: message))
        },
        primaryButton: { title, systemImage, action in
            AnyView(
                Button(action: action) {
                    Label(title, systemImage: systemImage)
                }
            )
        },
        chatMessage: { isUser, text in
            AnyView(ReferenceChatMessage(isUser: isUser, text: text))
        },
        composer: { text, busy, send, stop in
            AnyView(ReferenceComposer(text: text, busy: busy, send: send, stop: stop))
        },
        toolCall: { name, detail in
            AnyView(ReferenceToolCall(name: name, detail: detail))
        },
        feedbackButtons: { rating, onRate in
            AnyView(ReferenceFeedbackButtons(rating: rating, onRate: onRate))
        }
    )
}

private struct AppComponentsKey: EnvironmentKey {
    static let defaultValue = AppComponents.reference
}

public extension EnvironmentValues {
    var appComponents: AppComponents {
        get { self[AppComponentsKey.self] }
        set { self[AppComponentsKey.self] = newValue }
    }
}

// MARK: - Reference components

private struct ReferenceProductRow: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSystem.Spacing.xs) {
            HStack(alignment: .firstTextBaseline, spacing: DesignSystem.Spacing.s) {
                Text(product.name)
                    .font(.headline)
                Spacer(minLength: DesignSystem.Spacing.s)
                Text(DesignSystem.price(cents: product.priceCents))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            if !product.description.isEmpty {
                Text(product.description)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, DesignSystem.Spacing.xs)
        .accessibilityElement(children: .combine)
    }
}

private struct ReferenceEmptyState: View {
    let title: String
    let message: String?

    var body: some View {
        VStack(spacing: DesignSystem.Spacing.s) {
            Text(title)
                .font(.headline)
            if let message {
                Text(message)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(DesignSystem.Spacing.l)
    }
}

private struct ReferenceChatMessage: View {
    let isUser: Bool
    let text: String

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: DesignSystem.Spacing.xl) }
            Text(text)
                .padding(.horizontal, DesignSystem.Spacing.m)
                .padding(.vertical, DesignSystem.Spacing.s)
                .background(
                    isUser ? Color.accentColor.opacity(0.16) : Color.secondary.opacity(0.12),
                    in: RoundedRectangle(
                        cornerRadius: DesignSystem.Radius.card,
                        style: .continuous
                    )
                )
            if !isUser { Spacer(minLength: DesignSystem.Spacing.xl) }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(isUser ? "You" : "Assistant"): \(text)")
    }
}

private struct ReferenceComposer: View {
    @Binding var text: String
    let busy: Bool
    let send: () -> Void
    let stop: () -> Void

    var body: some View {
        HStack(spacing: DesignSystem.Spacing.s) {
            TextField("Ask a question…", text: $text, axis: .vertical)
                .lineLimit(1...4)
                .textFieldStyle(.roundedBorder)
                .onSubmit(send)
            Button(busy ? "Stop" : "Send", action: busy ? stop : send)
                .buttonStyle(.borderedProminent)
                .disabled(
                    !busy && text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
        }
    }
}

private struct ReferenceToolCall: View {
    let name: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: DesignSystem.Spacing.xs) {
            Label(name, systemImage: "wrench.and.screwdriver")
                .font(.caption.weight(.semibold))
            if !detail.isEmpty {
                Text(detail)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(DesignSystem.Spacing.s)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: DesignSystem.Radius.control))
    }
}

private struct ReferenceFeedbackButtons: View {
    let rating: Int?
    let onRate: (Int) -> Void

    var body: some View {
        if rating != nil {
            Text("Thanks for the feedback.")
                .font(.caption)
                .foregroundStyle(.secondary)
        } else {
            HStack(spacing: DesignSystem.Spacing.s) {
                Button("Helpful") { onRate(5) }
                    .buttonStyle(.bordered)
                Button("Not helpful") { onRate(1) }
                    .buttonStyle(.bordered)
            }
        }
    }
}
