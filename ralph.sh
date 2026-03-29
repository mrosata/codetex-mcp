# set error mode to ensure any errors are thrown
set -e

if [ -z "$1" ]; then
	echo "Usage: $0 <iterations>"
	exit 1
fi

# result=$(claude --permission-mode acceptEdits -p "study ./.ralph/prd.json

for ((i=1; i<=$1; i++)); do
	echo "--------------------------------"
	echo "Iteration $i"
	echo "--------------------------------"
	result=$(claude --dangerously-skip-permissions -p "study ./.ralph/prd.json

1. Find the highest-priority item to work on (ignore anything with passes: true) and work only on that item. This should be the one YOU decide has the highest priority - not necessarily the first item in the list.
2. Check that the types check (if available) and that the tests pass (if available).
3. Update the PRD with the work that was done.
4. Append your progress to the progress.md file. Use this to leave a note for the next person workin in the codebase.
5. Make a git commit of that feature.

ONLY WORK ON A SINGLE FEATURE.
If, while implementing the feature, you notice the PRD is complete, output <PROMISE>COMPLETE</PROMISE>.

If you need additional permissions to complete a task, first double-check that you don't already have the permission. If you have the necessary permission, then proceed to use it. Else print the permissions you need along with <PROMISE>NEED_PERMISSIONS</PROMISE> and exit. I will add them to the .claude/settings.local.json file and re-run.
")

	echo "$result"
	echo ""

	if [[ "$result" == *"<PROMISE>NEED_PERMISSIONS</PROMISE>"* ]]; then
		exit 1
	fi
	if [[ "$result" == *"<PROMISE>COMPLETE</PROMISE>"* ]]; then
		echo "PRD complete, exiting."
		afplay /System/Library/Sounds/Hero.aiff
		exit 0
	fi
done
