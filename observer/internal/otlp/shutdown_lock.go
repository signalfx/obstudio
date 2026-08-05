package otlp

import (
	"context"
	"sync"
	"time"
)

func lockRWMutexForShutdown(ctx context.Context, mu *sync.RWMutex) (func(), bool) {
	if mu.TryLock() {
		return mu.Unlock, true
	}
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil, false
		case <-ticker.C:
			if mu.TryLock() {
				return mu.Unlock, true
			}
		}
	}
}
