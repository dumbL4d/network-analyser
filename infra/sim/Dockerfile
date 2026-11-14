# A simulated network device: an Alpine container that answers ping.
#
# iproute2 provides `tc`. The chaos agent uses it (tc netem) to add delay,
# jitter and packet loss to a device; without chaos it is never run.
FROM alpine:3.20

RUN apk add --no-cache iproute2

CMD ["sleep", "infinity"]
