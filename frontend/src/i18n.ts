import { getRequestConfig } from "next-intl/server";

export const locales = ["en", "pl"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";

export default getRequestConfig(async ({ requestLocale }) => {
  const locale = await requestLocale;
  const safeLocale = locales.includes(locale as Locale) ? (locale as Locale) : defaultLocale;

  return {
    locale: safeLocale,
    messages: (await import(`../messages/${safeLocale}.json`)).default,
  };
});
