import createMiddleware from "next-intl/middleware";

export default createMiddleware({
  locales: ["en", "pl"],
  defaultLocale: "en",
  localePrefix: "always",
});

export const config = {
  // Localize every user-facing route, including unprefixed paths such as
  // `/login` and `/register`. Exclude Next internals, API handlers and files.
  matcher: ["/((?!api|_next|.*\\..*).*)"],
};
