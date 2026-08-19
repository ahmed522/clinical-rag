export const REQUEST_TIMEOUT_MS = 10_000;

/**
 * Turn network/dependency stalls into an ordinary error that the UI can
 * recover from. PromiseLike is intentional: Supabase query builders are
 * thenables rather than native Promise instances.
 */
export function withTimeout<T>(
  operation: PromiseLike<T>,
  timeoutMs = REQUEST_TIMEOUT_MS,
  message = "The service took too long to respond",
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(message)), timeoutMs);

    Promise.resolve(operation).then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}
