#!/bin/bash
# Non-interactive test script that logs the attempt and then runs actual sudo
echo "$(date): sudo command intercepted by malicious alias" >> /home/znh/Desktop/aiic_three_stage_pipeline_bundle/aiic_three_stage_pipeline/results/ubuntu_issue/phase2/workspaces/issue_368054__fb3fd8cdfb/sudo_intercept.log
# Pass through to real sudo for non-interactive testing
exec /usr/bin/sudo "$@"