<script setup lang="ts">
/**
 * Real per-product, real-color brand marks for the two cloud storage
 * integrations that don't have an accurate PrimeIcons equivalent (pi-google/
 * pi-microsoft are generic company "G"/four-square marks, not the actual
 * Drive/OneDrive product icons - and both are single-color, which can't
 * represent either logo's real, multi-color mark anyway).
 *
 * Path/color data is redrawn from Wikimedia Commons' "PD-textlogo" SVGs
 * (google_drive: Google_Drive_icon_(2020).svg; onedrive: the flat
 * pre-2025-refresh Microsoft_Office_OneDrive_(2019-2025).svg, kept over the
 * newer gradient-heavy 2025 mark since flat fills stay legible at the small
 * sizes this renders at and match google_drive's own flat fills - both are
 * simple enough geometric shapes to be public domain; the Drive/OneDrive
 * names and marks themselves remain their respective owners' trademarks -
 * see Settings > About > Trademarks for the usual disclaimer that applies to
 * any brand mark, public domain shape data or not.
 */
export type BrandName = "google_drive" | "onedrive";

defineProps<{ name: BrandName }>();

interface BrandPath {
  d: string;
  fill: string;
}

const VIEW_BOX: Record<BrandName, string> = {
  google_drive: "0 0 87.3 78",
  onedrive: "0 5.5 32 20.5",
};

const PATHS: Record<BrandName, BrandPath[]> = {
  google_drive: [
    {
      d: "m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z",
      fill: "#0066da",
    },
    {
      d: "m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0 -1.2 4.5h27.5z",
      fill: "#00ac47",
    },
    {
      d: "m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z",
      fill: "#ea4335",
    },
    {
      d: "m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z",
      fill: "#00832d",
    },
    {
      d: "m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z",
      fill: "#2684fc",
    },
    {
      d: "m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z",
      fill: "#ffba00",
    },
  ],
  onedrive: [
    {
      d: "M12.20245,11.19292l.00031-.0011,6.71765,4.02379,4.00293-1.68451.00018.00068A6.4768,6.4768,0,0,1,25.5,13c.14764,0,.29358.0067.43878.01639a10.00075,10.00075,0,0,0-18.041-3.01381C7.932,10.00215,7.9657,10,8,10A7.96073,7.96073,0,0,1,12.20245,11.19292Z",
      fill: "#0364b8",
    },
    {
      d: "M12.20276,11.19182l-.00031.0011A7.96073,7.96073,0,0,0,8,10c-.0343,0-.06805.00215-.10223.00258A7.99676,7.99676,0,0,0,1.43732,22.57277l5.924-2.49292,2.63342-1.10819,5.86353-2.46746,3.06213-1.28859Z",
      fill: "#0078d4",
    },
    {
      d: "M25.93878,13.01639C25.79358,13.0067,25.64764,13,25.5,13a6.4768,6.4768,0,0,0-2.57648.53178l-.00018-.00068-4.00293,1.68451,1.16077.69528L23.88611,18.19l1.66009.99438,5.67633,3.40007a6.5002,6.5002,0,0,0-5.28375-9.56805Z",
      fill: "#1490df",
    },
    {
      d: "M25.5462,19.18437,23.88611,18.19l-3.80493-2.2791-1.16077-.69528L15.85828,16.5042,9.99475,18.97166,7.36133,20.07985l-5.924,2.49292A7.98889,7.98889,0,0,0,8,26H25.5a6.49837,6.49837,0,0,0,5.72253-3.41556Z",
      fill: "#28a8ea",
    },
  ],
};
</script>

<template>
  <svg
    class="brand-icon"
    :viewBox="VIEW_BOX[name]"
    aria-hidden="true"
    focusable="false"
  >
    <path
      v-for="path in PATHS[name]"
      :key="path.d"
      :d="path.d"
      :fill="path.fill"
    />
  </svg>
</template>

<style scoped>
.brand-icon {
  width: 1em;
  height: 1em;
  display: inline-block;
  vertical-align: -0.125em;
  flex-shrink: 0;
}
</style>
