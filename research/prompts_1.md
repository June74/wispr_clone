# Prompt 1
## GPT-6 Astra Light

You are to take the role of a professional senior devleoper that has created projects such as wisprflow, openwhispr, and other voice controlled applications. 

I want to simply plan this out first. 

For now, here are the core features I know it must have. 

1. push to trigger button that begins voice transcription. 

2. Speech to text. 

3. Recording audio. 

4. Injection of the text into where my cursor is. 

5. Cleanup of unnecessary phrases such as "uh" "um" 

6. A UI that allows for easy control over AI models connected to this

7. The ability to utilize sst and cleanup models. 

8. Ability to add a dictionary specific for the user (me)



This is all I understand for now, are there any additional features? 


# Prompt 2
## GPT-6 Astra Light

Here's what I understand so far. 

Within a UI that opens locally, we are able to set either a push to talk key or a start/stop/cancel key. 

We are also able to set the input device and test it within this UI as well. 

We are also able to set specific words that are not natural, so perhaps game usernames, scientific words, and words that will "autocorrect" to something else or has a chance to, should be stored within a user specific database. 

We intially begin by triggering through the button set in our settings. 

After that, recording begins, and a small overlay HUD shows recording, transcribing, cleaning, or an error. Here, instead of displaying "transcribing" "cleaning" it should just be a waveform of lines that fluctuate with our speaking. 

Then it checks if the destination is still the same as when it first began. Keep the audio transcription held and able to be pasted in case the user would like to move it somewhere else. 

ONLY transcribe, no commands other than registered ones or injections should happen. 

If insertion fails, contain the current audio transcription, offer the user to copy or retry. Cleanup should not fail, but yes, keep the original available. No duplicates. 

Cleanup will remove fillers and not change the audio transcription. 

Audio and transcription up to the 10 most recent turns should be saved in a temporary database, and can be deleted with "delete" within the local ui. 10 most recent turns for only up to 24 hours. 




I use windows but use wsl/ubuntu for coding/development, where all of my coding apps and tools are stored. 

The trigger should be both viable. 

Recording audio means tempoary capture for transcription. 


Just making sure, but this is all of our wispr clone features?



# Prompt 3
## GPT-6 Astra Light


The waveform should be 1. blue when not being used. 2. green when being used. 3. yellow when loading or processing. 4. red if there is an error. Only the waveforms should be "moving" when it is green/being used. 

Add that requirement to remove fillers while preserving meaning. 

The 24 hours deadline was so that we do not need a permanent database for storing the audio and transcripts. Hence, we only store the 10 most recent runs within a 24 hour time. It should be like a sliding window, where if the original 10 stored was 1 2 3 4 5 6 7 8 9 10, and 11 was transcribed within 24 hours, it should become 2 3 4 5 6 7 8 9 10 11, with 1 deleted. However, if numbers 2 3 and 4 were done 24 hours ago, it should be deleted. 


# Prompt 4
## GPT-6 Astra Light

In what features do we need AI models? 

I know for one we need speech to text, as well as a good base model for cleanup. Do we need anything else? 

For intended destination, have it set in stone. For example, when the user clicks on a textbox, a file, or anywhere, then clicks on the button to begin recording audio, have the cursor be immovable. 

# Prompt 5
## GPT-6 Astra Light

What speech-to-text models should I use? For open-weights (local), I was considering Voxtral small, Mistral. If i was to pay for something, I think MAI-transcribe-2 would be best. Am I able to run Voxtral small on my computer locally? 

What model should I use for cleanup? 