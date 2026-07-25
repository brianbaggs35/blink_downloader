<script setup lang="ts">
import Button from "primevue/button";
import { useRouter } from "vue-router";

import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";

const router = useRouter();
</script>

<template>
  <section>
    <PageHeader
      title="Library"
      description="Your synced clips with thumbnails, playback, and AI summaries."
    />
    <EmptyState
      icon="pi pi-images"
      title="No clips yet"
      description="Link your Blink account and clips will start syncing automatically, complete with thumbnails and AI analysis."
    >
      <template #actions>
        <Button
          label="Open Settings"
          icon="pi pi-cog"
          severity="secondary"
          outlined
          data-testid="go-settings"
          @click="router.push({ name: 'settings' })"
        />
      </template>
    </EmptyState>
  </section>
</template>
