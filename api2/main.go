package main

import (
	"encoding/json"
	"flag"
	"log"
	"net/http"
	"runtime"
	"time"
)

func main() {
	addr := flag.String("addr", ":8080", "listen address")
	sleep := flag.Duration("sleep", 500*time.Millisecond, "simulated IO sleep per request")
	flag.Parse()

	mux := http.NewServeMux()

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"status": "ok", "server": "api2-go"})
	})

	mux.HandleFunc("/slow", func(w http.ResponseWriter, r *http.Request) {
		// IO バウンドな処理をシミュレート（ブロッキング）。Go はリクエストごとに
		// goroutine で処理されるため、このブロックが他のリクエストを止めることはない。
		time.Sleep(*sleep)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status":   "ok",
			"server":   "api2-go",
			"sleep_ms": (*sleep).Milliseconds(),
			"gomaxprocs": runtime.GOMAXPROCS(0),
		})
	})

	srv := &http.Server{
		Addr:         *addr,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	log.Printf("api2 (go) listening on %s, sleep=%v, GOMAXPROCS=%d", *addr, *sleep, runtime.GOMAXPROCS(0))
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("server error: %v", err)
	}
}
