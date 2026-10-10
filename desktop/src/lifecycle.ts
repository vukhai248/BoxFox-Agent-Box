/** Cleanup also runs on startup failure and explicit app.exit (which skips will-quit). */
export class DesktopCleanup {
  private tasks: Array<() => void | Promise<void>> = []
  private running: Promise<void> | null = null

  add(task: () => void | Promise<void>): void {
    this.tasks.push(task)
  }

  run(onError: (error: unknown) => void): Promise<void> {
    if (this.running) return this.running
    this.running = (async () => {
      while (this.tasks.length) {
        try {
          await this.tasks.pop()!()
        } catch (error) {
          onError(error)
        }
      }
    })()
    return this.running
  }
}
