FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/api2 -ldflags="-s -w" .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl
COPY --from=builder /out/api2 /api2
EXPOSE 8080
ENTRYPOINT ["/api2"]
