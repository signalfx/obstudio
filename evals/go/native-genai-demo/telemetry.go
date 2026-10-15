package main

import "context"

func configureTelemetry(_ context.Context, _ *App) (func(context.Context) error, error) {
	return func(context.Context) error { return nil }, nil
}
