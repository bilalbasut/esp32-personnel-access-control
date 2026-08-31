import { ref, onMounted, onUnmounted } from 'vue';

export function usePolling(fetchFn, intervalMs = 5000) {
  const data = ref({});
  const error = ref(null);
  const loading = ref(true);
  let timer = null;

  const execute = async () => {
    try {
      const res = await fetchFn();
      data.value = res;
      error.value = null;
    } catch (err) {
      error.value = err.message || 'Data retrieval failed';
    } finally {
      loading.value = false;
    }
  };

  onMounted(() => {
    execute();
    timer = setInterval(execute, intervalMs);
  });

  onUnmounted(() => {
    if (timer) clearInterval(timer);
  });

  return { data, error, loading, refresh: execute };
}