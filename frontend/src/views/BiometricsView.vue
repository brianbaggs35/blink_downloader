<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
</script>

<template>
  <section>
    <PageHeader
      title="Biometrics"
      description="Teach the system who your family and friends are — privately, on-device."
    />
    <EmptyState
      icon="pi pi-id-card"
      title="Facial recognition is coming"
      description="Enroll people from real camera frames for best accuracy. Face data never leaves this machine and is never sent to any cloud provider."
    />
  </section>
</template>
