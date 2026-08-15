import createMiddleware from "next-intl/middleware";

export default createMiddleware({
  locales: ["en", "pl"],
  defaultLocale: "en",
  localePrefix: "always",
});

export const config = {
  matcher: ["/", "/(en|pl)/:path*"],
};
