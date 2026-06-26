FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY . .
RUN go mod download
RUN CGO_ENABLED=0 go build -o correctover-mcp-server .

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=builder /build/correctover-mcp-server .

ENTRYPOINT ["/app/correctover-mcp-server"]
