<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
</script>

<template>
  <section>
    <PageHeader
      title="Vehicles"
      description="Protect your vehicles with outlines, proximity zones, and alerts."
    />
    <EmptyState
      icon="pi pi-car"
      title="Vehicle protection is coming"
      description="Draw an outline around each vehicle, and the system will learn it — alerting you when someone approaches within a distance you choose, day or night."
    />
  </section>
</template>
