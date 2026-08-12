# mc-computer client aliases
#
# Source this from your shell rc:
#     [[ -f ~/mc-computer/client/.bash_aliases ]] && source ~/mc-computer/client/.bash_aliases
#
# Works in bash and zsh. Nothing here holds a secret; everything runs over ssh.

MC_HOST="${MC_HOST:-mc-public}"

# --- logs -------------------------------------------------------------------
# The interesting lines: what triggered a turn, what it said, what it ran.
alias mccomplog='ssh "$MC_HOST" "tail -n 0 -f /var/lib/mcbot/logs/comp.log" | grep --line-buffered -E "\[wake\]|\[computer\]|\[action\]|\[error\]|\[warn\]"'
# Everything, unfiltered — for when the filtered view is hiding the problem.
alias mccompall='ssh "$MC_HOST" "tail -n 0 -f /var/lib/mcbot/logs/comp.log"'
# Raw Minecraft server log.
alias mclogs='ssh "$MC_HOST" "docker logs -f --tail 50 mc"'

# What each turn costs, live, paired with the message that caused it.
#   mccost            follow new turns as they happen
#   mccost today      every turn so far today, with a total
mccost() {
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
        END { if (count) printf "%s\n%d turns · $%.4f total · $%.4f average\n", \
                     "----------------------------------------", count, total, total/count }
    '
    if [ "$1" = "today" ]; then
        ssh "$MC_HOST" "grep -aE '$filter' /var/lib/mcbot/logs/comp.log | grep -a \"^\\[$(date +%Y-%m-%d)\"" \
            | awk "$awk_prog"
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
alias mcdeploy='~/mc-computer/client/deploy.sh'
