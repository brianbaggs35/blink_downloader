<script setup lang="ts">
import EmptyState from "@/components/EmptyState.vue";
import PageHeader from "@/components/PageHeader.vue";
</script>

<template>
  <section>
    <PageHeader
      title="Storage"
      description="Archived clips and external storage destinations."
    />
    <EmptyState
      icon="pi pi-database"
      title="Archive management is coming"
      description="Manage archived clips locally, then connect Google Drive, S3, or OneDrive to keep long-term copies off-device."
    />
  </section>
</template>
