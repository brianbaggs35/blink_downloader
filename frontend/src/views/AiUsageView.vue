<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
</script>

<template>
  <section>
    <PageHeader
      title="AI Usage"
      description="Token consumption, request volume, and cost per provider."
    />
    <EmptyState
      icon="pi pi-chart-bar"
      title="Usage analytics are coming"
      description="Track tokens and spend across OpenAI, Anthropic, Ollama, and Moondream — per clip, per camera, and over time."
    />
  </section>
</template>
