<script setup lang="ts">
const technologies = [
  { name: "FastAPI", href: "https://fastapi.tiangolo.com/" },
  { name: "SQLAlchemy", href: "https://www.sqlalchemy.org/" },
  { name: "PostgreSQL + pgvector", href: "https://github.com/pgvector/pgvector" },
  { name: "Redis + arq", href: "https://arq-docs.helpmanual.io/" },
  { name: "Vue.js", href: "https://vuejs.org/" },
  { name: "PrimeVue", href: "https://primevue.org/" },
  { name: "insightface + onnxruntime", href: "https://github.com/deepinsight/insightface" },
  { name: "video.js", href: "https://videojs.com/" },
  { name: "FFmpeg", href: "https://ffmpeg.org/" },
  { name: "Playwright", href: "https://playwright.dev/" },
];
</script>

<template>
  <div class="panels">
    <article class="panel">
      <h3 class="panel-title">
        Open source
      </h3>
      <p class="panel-hint">
        Blink AI Security is free, open-source software, maintained by Brian
        Baggs.
      </p>
      <a
        class="about-link"
        href="https://github.com/brianbaggs35/blink_downloader"
        target="_blank"
        rel="noopener noreferrer"
        data-testid="about-repo-link"
      >
        <i
          class="pi pi-github"
          aria-hidden="true"
        />
        View source on GitHub
      </a>
    </article>

    <article class="panel">
      <h3 class="panel-title">
        Credits
      </h3>
      <p class="panel-hint">
        Built on the work of these projects.
      </p>
      <p class="panel-body-text">
        Every Blink API call — account login, camera discovery, clip sync,
        live snapshots and recordings — goes through
        <a
          href="https://github.com/fronzbot/blinkpy"
          target="_blank"
          rel="noopener noreferrer"
          data-testid="about-blinkpy-link"
        >blinkpy</a>, the unofficial, community-maintained Blink API client
        this project depends on for all device communication. This project
        isn't affiliated with Blink or Amazon.
      </p>
    </article>

    <article class="panel">
      <h3 class="panel-title">
        Trademarks
      </h3>
      <p class="panel-hint">
        Third-party names and marks referenced by the Storage integrations
        feature.
      </p>
      <p class="panel-body-text">
        Google Drive is a trademark of Google LLC. Microsoft OneDrive is a
        trademark of Microsoft Corporation. Amazon S3 is a trademark of
        Amazon.com, Inc. or its affiliates. This project is not affiliated
        with, endorsed by, or sponsored by Google, Microsoft, or Amazon. The
        Google Drive and OneDrive icons shown on the Integrations and Storage
        pages are
        <a
          href="https://github.com/Templarian/MaterialDesign"
          target="_blank"
          rel="noopener noreferrer"
        >Pictogrammers Material Design Icons</a> (Apache-2.0) - used to
        identify the products, not to imply endorsement.
      </p>
    </article>

    <article class="panel">
      <h3 class="panel-title">
        Built with
      </h3>
      <p class="panel-hint">
        The rest of the stack — see
        <a
          href="https://github.com/brianbaggs35/blink_downloader/blob/main/docs/ARCHITECTURE.md"
          target="_blank"
          rel="noopener noreferrer"
        >docs/ARCHITECTURE.md</a> for how it fits together.
      </p>
      <ul class="tech-list">
        <li
          v-for="tech in technologies"
          :key="tech.name"
        >
          <a
            :href="tech.href"
            target="_blank"
            rel="noopener noreferrer"
          >{{ tech.name }}</a>
        </li>
      </ul>
    </article>
  </div>
</template>

<style scoped>
.panels {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  align-items: start;
}

.panel {
  padding: 22px 24px;
  border-radius: 14px;
  border: 1px solid var(--p-surface-200);
  background: var(--p-surface-0);
}

.blink-dark .panel {
  border-color: var(--p-surface-800);
  background: color-mix(in srgb, var(--p-surface-900) 60%, transparent);
}

.panel-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}

.panel-hint {
  margin: 4px 0 16px;
  font-size: 0.82rem;
  color: var(--p-surface-500);
}

.panel-body-text {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.6;
  color: var(--p-surface-700);
}

.blink-dark .panel-body-text {
  color: var(--p-surface-300);
}

.panel-body-text a,
.panel-hint a {
  color: var(--p-primary-600);
  font-weight: 600;
  text-decoration: none;
}

.blink-dark .panel-body-text a,
.blink-dark .panel-hint a {
  color: var(--p-primary-300);
}

.panel-body-text a:hover,
.panel-hint a:hover {
  text-decoration: underline;
}

.about-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--p-primary-600);
  text-decoration: none;
}

.blink-dark .about-link {
  color: var(--p-primary-300);
}

.about-link:hover {
  text-decoration: underline;
}

.tech-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.tech-list li {
  font-size: 0.85rem;
}

.tech-list a {
  color: var(--p-primary-600);
  font-weight: 600;
  text-decoration: none;
}

.blink-dark .tech-list a {
  color: var(--p-primary-300);
}

.tech-list a:hover {
  text-decoration: underline;
}
</style>
