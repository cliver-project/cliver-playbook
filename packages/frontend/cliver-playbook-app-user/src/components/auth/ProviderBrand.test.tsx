import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OAuthProviderButton } from "../../api/auth.ts";
import { ProviderIcon, providerLabel, resolveProviderLabel } from "./ProviderBrand.tsx";

const wechat: OAuthProviderButton = {
  key: "wechat",
  label: "WeChat",
  labels: { zh: "微信", "zh-cn": "微信 CN" },
  brand_color: "#07C160",
};

describe("resolveProviderLabel", () => {
  it("tries the full locale tag, then the base tag, then the default", () => {
    expect(resolveProviderLabel("WeChat", { zh: "微信", "zh-cn": "微信 CN" }, "zh-CN")).toBe(
      "微信 CN",
    );
    expect(resolveProviderLabel("WeChat", { zh: "微信", "zh-cn": "微信 CN" }, "zh-TW")).toBe("微信");
    expect(resolveProviderLabel("WeChat", { en: "WeChat" }, "fr-FR")).toBe("WeChat");
    expect(resolveProviderLabel("Alipay", undefined, "zh-CN")).toBe("Alipay");
  });

  it("resolves a provider object for the active language", () => {
    expect(providerLabel(wechat, "zh-CN")).toBe("微信 CN");
    expect(providerLabel(wechat, "en-US")).toBe("WeChat");
  });
});

describe("ProviderIcon", () => {
  it("uses the localized label for the fallback initial", () => {
    const { container, rerender } = render(<ProviderIcon provider={wechat} label="微信" />);
    expect(container.textContent).toBe("微");

    rerender(<ProviderIcon provider={wechat} label="WeChat" />);
    expect(container.textContent).toBe("W");
  });

  it("prefers the configured image over the initial badge", () => {
    const provider = { ...wechat, icon: "/brand/wechat.svg" };
    const { container } = render(<ProviderIcon provider={provider} label="微信" />);

    expect(container.querySelector("img")?.getAttribute("src")).toBe("/brand/wechat.svg");
    expect(container.textContent).toBe("");
  });

  it("renders nothing without an image or brand color", () => {
    const provider: OAuthProviderButton = { key: "plain", label: "Plain" };
    const { container } = render(<ProviderIcon provider={provider} />);

    expect(container.innerHTML).toBe("");
  });
});
