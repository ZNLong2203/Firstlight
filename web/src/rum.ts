import { datadogRum } from "@datadog/browser-rum";

// RUM starts only when the build received an application id and client token.
export function startRum(): void {
  const applicationId = import.meta.env.VITE_DD_RUM_APPLICATION_ID;
  const clientToken = import.meta.env.VITE_DD_RUM_CLIENT_TOKEN;
  if (!applicationId || !clientToken) return;
  datadogRum.init({
    applicationId,
    clientToken,
    site: import.meta.env.VITE_DD_SITE || "datadoghq.com",
    service: "firstlight-web",
    env: import.meta.env.VITE_DD_ENV || "local",
    version: import.meta.env.VITE_DD_VERSION || "dev",
    sessionSampleRate: 100,
    sessionReplaySampleRate: 100,
    trackUserInteractions: true,
    defaultPrivacyLevel: "mask-user-input",
    allowedTracingUrls: [window.location.origin],
  });
}
