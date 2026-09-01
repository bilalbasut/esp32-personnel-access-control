import { ref, computed, watch } from 'vue';

// Client-side pagination over a reactive array ref. The backend list
// endpoints (cards, employees) don't support limit/offset - they're read via
// the ORM as full result sets - so paging here is the simplest fix that
// needs no API changes; these are staff/card directories, not event logs,
// so the full list is always small enough to fetch in one call.
export function usePagination(itemsRef, pageSize = 10) {
  const page = ref(1);

  const totalPages = computed(() => Math.max(1, Math.ceil((itemsRef.value || []).length / pageSize)));

  // If the list shrinks (e.g. a delete drops the last item off the last
  // page) and the current page no longer exists, step back onto the new
  // last page instead of showing an empty page.
  watch(totalPages, (max) => {
    if (page.value > max) page.value = max;
  });

  const pageItems = computed(() => {
    const start = (page.value - 1) * pageSize;
    return (itemsRef.value || []).slice(start, start + pageSize);
  });

  const goTo = (n) => { page.value = Math.min(Math.max(1, n), totalPages.value); };
  const next = () => goTo(page.value + 1);
  const prev = () => goTo(page.value - 1);

  return { page, totalPages, pageItems, goTo, next, prev };
}
