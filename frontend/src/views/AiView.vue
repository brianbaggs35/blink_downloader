<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
</script>

<template>
  <section>
    <PageHeader
      title="AI"
      description="How your clips are being analyzed: providers, models, and detection activity."
    />
    <EmptyState
      icon="pi pi-sparkles"
      title="AI insights are coming"
      description="Every clip gets a short summary and a suspicion assessment. This tab will show provider status, recent detections, and accuracy trends built from your feedback."
    />
  </section>
</template>
