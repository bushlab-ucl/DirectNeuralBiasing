



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Real-time detection of SW
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

% The stimulation (index of marker) is put at the expected following
% up-state, based on our 2023 paper, since we probably won't have enough
% data to measure the individual delay of patients (wake SW are much less
% frequent than sleep SW)

% The periodic update of the threshold is not introduced in this 1st
% version (this threshold is mainly intended to control for the change of
% SW amplitude across night, which should thus not affect recording during
% wakefulness)

% The mean amplitude in the 2023 paper is -2419 microV. The two consecutive
% 0-crossing are at -0.147 s and 0.163 (hence, half a period lasts ~300
% ms). Based on their oscillatory frequency, the mean delay between two
% consecutive 0-crossings is 0.3571 s

% During late sleep, there is less multipeaks SW. Multipeak SW could thus
% be less associated with a large homeostatic impact. cf. Riedner et al.
% (2007) Sleep. Here, we thus optimize the detection for single peak SWs

% All arbitrary numbers have been customized based on current data

% Input: matrix 'mat' with electrode x timeframes

clearvars -except mat

sf = 512;
fc_low = 0.25;
fc_high = 4;
filter_order = 2;
delay_to_up_state_s = 0.300;
refractory_s = 2.5;     % from the end of a candidate wave to the next tested timeframe
detection_by_absolute_amplitude = 0;
detection_by_zero_crossing = 1;
min_ZeroCrossing_s = 0.25;
max_ZeroCrossing_s = 1;
threshold_sinusoid = 0.6; % r coefficient. Minimal correlation between perfect
                          % sinusoid and the candidate wave. This is to
                          % avoid identifying waves with multiple peaks.
                          % Also inspired by the works of Talami group

min_ZeroCrossing = min_ZeroCrossing_s * sf;
max_ZeroCrossing = max_ZeroCrossing_s * sf;
refractory = refractory_s * sf;
delay_to_up_state = delay_to_up_state_s * sf;
[b_low a_low] = butter(filter_order, 2*fc_low/sf,'high'); % coefficients of the high pass-filter
[b_high a_high] = butter(filter_order, 2*fc_high/sf,'low'); % coefficients of the low pass-filter

dat = filter(b_low, a_low, mat); % forward filtering (high-pass)
thedata = filter(b_high, a_high, dat)'; % forward filtering (low-pass)

absolute_min_threshold = prctile(abs(hilbert(thedata(1 : sf*600))), 90);           % take the first 10 min to calculate the threshold
absolute_max_threshold = 2.5 * prctile(abs(hilbert(thedata(1 : sf*600))), 90);     % prevent from detecting IEDs

n = 2;     % formally this should starts after the period used to define 'absolute_max/min_threshold'
i = 1;
tf_idx = 1;                           % safety check
negD = 0;                             % counts # tf for candidate waves
onsetSW = 0;
while n <= length(thedata)
    all_evaluated_tf(tf_idx) = n;     % safety check
    tf_idx = tf_idx + 1;              % safety check
    if thedata(n) < 0
        if thedata(n-1) >= 0 || n == 2     % basically, check whether it's a zero crossing
            onsetSW = n;
        end
        negD = negD + 1;
        n = n + 1;
    else
        if onsetSW ~= 0 && ~isnan(onsetSW)     % basically, data were negative at the previous timeframe

            offsetSW = n;
            SWpeak_idx = onsetSW + find(thedata(onsetSW : offsetSW) == min(thedata(onsetSW : offsetSW)));     % find the timeframe of minima within filtered data
            SWpeak_idx_raw = onsetSW + find(mat(onsetSW : offsetSW) == min(mat(onsetSW : offsetSW)));         % find the timeframe of minima within unfiltered data

            % Design the corresponding sinusoid
            dt = 1/sf;                                      % seconds per sample
            StopTime = (offsetSW - onsetSW)/sf;             % seconds
            t = (0:dt:StopTime-dt)';                        % seconds
            A = thedata(SWpeak_idx);                        % the amplitude is based on the filtered signal, but you will compare it with the amplitude of the raw signal
            F = 1/(((offsetSW-onsetSW) / sf)*2);            % sine wave frequency (hertz)
            osc = A * sin(2*pi*F*t);

            % If the candidate wave fulfill several criteria
            if negD > min_ZeroCrossing &&...                                             % the period has to be longer than a given threshold
                    negD < max_ZeroCrossing &&...                                        % the period has to be shorter than a given threshold
                    abs(thedata(SWpeak_idx)) > absolute_min_threshold &&...              % the amplitude of the filtered data has to be larger than a certain threshold
                    abs(mat(SWpeak_idx_raw)) < absolute_max_threshold &&...              % avoid IED confusion
                    corr(mat(1,onsetSW : offsetSW-1)', osc) > threshold_sinusoid &&...   % optimize the detection of single-peak wave
                    offsetSW - SWpeak_idx < delay_to_up_state                            % the delay between the end of a half-wave and its minima has to be shorter than the delay between the minima and the trigger

                % The trigger for the up-state is at a given delay
                % from the identified negative peak.
                mrk(i) = SWpeak_idx + delay_to_up_state;
                mrk_MaxNegAmp(i) = SWpeak_idx;             % safety check
                i = i+1;
                n = n + refractory;
                onsetSW = nan;
            else
                n = n + 1;
                onsetSW = nan;
            end
            negD = 0;
        else
            n = n + 1;
        end
    end

end


% Verification purpose
mrk = round(mrk);
time = [-3 + (6/length(-sf*3 : sf*3)) : 6/length(-sf*3 : sf*3) : 3];
for i = 1 : length(mrk)
    if mrk(i) - sf*3 > 0 && mrk(i) + sf*3 < length(mat)
        plot(time, mat(1,mrk(i) + [-sf*3 : sf*3]), 'k')
        hold on
    end
end
vline(0)













