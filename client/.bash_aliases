# mc-computer client aliases
#
# Source this from your shell rc, from wherever the repo is checked out:
#     [[ -f /path/to/mc-computer/client/.bash_aliases ]] && source "$_"
#
# Works in bash and zsh. Nothing here holds a secret; everything runs over ssh.

MC_HOST="${MC_HOST:-mc-public}"

# Where this file was sourced from, so the repo path is not written down a second
# time and left to drift. Only mcdeploy needs it; everything else goes over ssh.
# The zsh form is kept behind eval so bash never tries to expand it.
if [ -n "${ZSH_VERSION:-}" ]; then
    MC_REPO="$(cd "$(dirname "$(eval 'print -r -- ${(%):-%x}')")/.." && pwd)"
else
    MC_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

# --- logs -------------------------------------------------------------------
# The interesting lines: what triggered a turn, what it said, what it ran.
alias mccomplog='ssh "$MC_HOST" "tail -n 0 -f /var/lib/mcbot/logs/comp.log" | grep --line-buffered -E "\[wake\]|\[computer\]|\[action\]|\[error\]|\[warn\]"'
# Everything, unfiltered — for when the filtered view is hiding the problem.
alias mccompall='ssh "$MC_HOST" "tail -n 0 -f /var/lib/mcbot/logs/comp.log"'
# Raw Minecraft server log.
alias mclogs='ssh "$MC_HOST" "docker logs -f --tail 50 mc"'

# What each turn costs, live, paired with the message that caused it.
#   mccost               follow new turns as they happen
#   mccost today         every turn so far today, with a total
#   mccost yesterday     every turn on the previous day
#   mccost 2026-08-09    every turn on an explicit date (YYYY-MM-DD)
mccost() {
    # Every dated form takes the same path: build the day, then select the log lines
    # that start with it. BSD date, because this runs on a Mac.
    local day=""
    case "$1" in
        "")          ;;
        today)       day="$(date +%Y-%m-%d)" ;;
        yesterday)   day="$(date -v-1d +%Y-%m-%d)" ;;
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
            # A well-formed date can still name a day that does not exist. BSD date
            # rolls 2026-02-30 forward to March, so compare what comes back.
            day="$(date -j -f %Y-%m-%d "$1" +%Y-%m-%d 2>/dev/null)"
            if [ "$day" != "$1" ]; then
                echo "mccost: not a real date: $1" >&2
                return 2
            fi
            ;;
        *)
            echo "mccost: unknown argument: $1" >&2
            echo "usage: mccost [today|yesterday|YYYY-MM-DD]" >&2
            return 2
            ;;
    esac

    # Pull the request lines as well as the cost lines, so each cost can be labelled
    # with the chat message that triggered it.
    local filter="turn complete|^\\[.*\\[wake\\]     \\| [A-Za-z0-9_]+:"
    local awk_prog='
        /\| [A-Za-z0-9_]+:/ {
            i = index($0, "| ")
            msg = substr($0, i + 2)
            next
        }
        /turn complete/ {
            ts = substr($0, 13, 8)
            n = split($0, a, "[$]")
            c = a[n] + 0
            total += c; count += 1
            if (msg == "") msg = "(no chat — login, backup check or interrupt)"
            printf "%s  $%6.4f  %s\n", ts, c, substr(msg, 1, 90)
            fflush()
            msg = ""
        }
        END {
            if (count) printf "%s\n%d turns · $%.4f total · $%.4f average\n", \
                     "----------------------------------------", count, total, total/count
            else if (day != "") printf "no turns on %s\n", day
        }
    '
    if [ -n "$day" ]; then
        ssh "$MC_HOST" "grep -aE '$filter' /var/lib/mcbot/logs/comp.log | grep -a \"^\\[$day\"" \
            | awk -v day="$day" "$awk_prog"
    else
        ssh "$MC_HOST" "tail -n 0 -f /var/lib/mcbot/logs/comp.log" \
            | grep --line-buffered -aE "$filter" | awk "$awk_prog"
    fi
}

# --- service control --------------------------------------------------------
# mccompctl status|restart|stop mcbot
alias mccompctl='ssh -t "$MC_HOST" "sudo systemctl"'

# --- server actions ---------------------------------------------------------
# Quote each argument for the remote shell. printf %q behaves the same in bash and
# zsh, so a MOTD containing spaces, quotes or an apostrophe survives the trip.
_mc_remote() {
    local cmd="$1"; shift
    local args=""
    local a
    for a in "$@"; do args="$args $(printf '%q' "$a")"; done
    ssh -t "$MC_HOST" "$cmd$args"
}

# mcrestart [seconds]   no arg = 60, 0 = immediately.
# Warnings at the starting figure then every remaining multiple of 15.
mcrestart() { _mc_remote /opt/mc/mcrestart "$@"; }

# motd "text" [-r [seconds]]   -r recreates the container so the change takes effect
motd() { _mc_remote /opt/mc/mcmotd "$@"; }

# What named places exist in the world: mcwhere [search term]
mcwhere() { _mc_remote /opt/mc/mcwhere "$@"; }

# What is inside a player's backpacks: mcbag <player>
mcbag() { _mc_remote /opt/mc/mcbag "$@"; }

# Ask the in-game computer something from here. Forks the live session, so it has
# full context and memory but neither interrupts nor waits on in-game work.
#   mcask "how much iron does PlayerName have?"
#   mcask --new "..."   start fresh instead of forking
mcask() {
    local args=""
    local a
    for a in "$@"; do args="$args $(printf '%q' "$a")"; done
    ssh "$MC_HOST" "/opt/mc/mcask$args"
}

# Is it running, healthy, and running the build you think it is?
alias mchealth='ssh "$MC_HOST" /opt/mc/mchealth'

# --- deployment -------------------------------------------------------------
alias mcdeploy='"$MC_REPO"/client/deploy.sh'
