<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
</script>

<template>
  <section>
    <PageHeader
      title="Live View"
      description="Watch your cameras in real time, snap screenshots, and save recordings."
    />
    <EmptyState
      icon="pi pi-video"
      title="Live view is coming in a future release"
      description="You'll be able to open a live stream per camera, capture stills, and record short videos straight into your Library."
    />
  </section>
</template>
